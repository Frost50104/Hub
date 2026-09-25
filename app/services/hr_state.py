"""Заморозка кадровых данных в Hub (16d, 0063): чьи кадровые поля и когда.

Правило одно: кадровые поля карточки человека ведёт auth, пока организация
`authoritative` в последнем ПОЛНОМ снимке справочников, — и во время ручного
окна каткатa. Источник — строка `hr_sync_state` тенанта, а НЕ флаг
потребителя: `hr_consumer_enabled=false` останавливает обновления, но не
открывает правку тенанта, которым владеет auth (иначе выключатель стал бы
способом править в обход auth, а следующий прогон молча перетёр бы правку).

Кассы (`account_kind = service`) заморозку не наследуют (требование 7): ключа
`hr` у них нет, их должность, точка и руководитель — поля Hub.

Решения — чистые функции (`derive_view`, `is_frozen`); БД-обёртки ниже только
читают строку. Тексты отказов — строкой: `extractErrorDetail` на фронте
словарь в `detail` не показывает.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_sync import HrSyncState

# Кадровые поля карточки — ровно те, что несёт блок `hr` (контракт 16d).
HR_PROFILE_FIELDS: tuple[str, ...] = (
    "hired_at",
    "org_role",
    "position_id",
    "store_id",
    "department_id",
    "franchisee_id",
    "manager_profile_id",
)

HR_FROZEN_DETAIL = (
    "Кадровые данные ведутся в auth — поменяйте их там, Hub обновит карточку "
    "в течение 15 минут. Если вы их не меняли — обновите страницу"
)
HR_TU_DETAIL = (
    "Закреплённые точки ведутся в auth. Остальные изменения карточки сохранены"
)
HR_DIRECTORY_DETAIL = "Справочник ведётся в auth — поменяйте его там"
HR_STORE_FRANCHISEE_DETAIL = (
    "Франчайзи точки ведётся в auth — поменяйте его там. Если вы его не меняли — "
    "обновите страницу"
)
HR_WINDOW_DETAIL = "Идёт перенос кадровых данных в auth — правка временно закрыта"
HR_RESTORE_DEACTIVATED_DETAIL = (
    "Учётка отключена в auth — включите её там, карточка вернётся сама"
)

# Состояния для интерфейса (строка над кадровым блоком карточки).
STATE_WINDOW = "window"  # ручное окно каткатa
STATE_BLOCKED = "blocked"  # предохранитель: изменения ждут hub-admin
STATE_PAUSED = "paused"  # заморожен, но применение для тенанта не включено
STATE_STALE = "stale"  # применения давно не было — auth недоступен или сбой
STATE_SYNCED = "synced"


@dataclass(frozen=True)
class HrView:
    frozen: bool
    window: bool
    state: str | None
    synced_at: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "frozen": self.frozen,
            "window": self.window,
            "state": self.state,
            "synced_at": self.synced_at,
        }


NOT_FROZEN = HrView(frozen=False, window=False, state=None, synced_at=None)


def is_frozen(row: HrSyncState | None) -> bool:
    return row is not None and (row.authoritative or row.cutover_freeze)


def in_window(row: HrSyncState | None) -> bool:
    return row is not None and row.cutover_freeze


def derive_view(
    row: HrSyncState | None,
    *,
    applying: bool,
    now: datetime,
    interval_sec: float,
) -> HrView:
    """Что показать над кадровым блоком. Не заморожен → `NOT_FROZEN`.

    «Давно» — дольше трёх интервалов синка: один пропущенный тик (рестарт,
    занятый замок) не должен пугать людей плашкой.
    """
    if not is_frozen(row):
        return NOT_FROZEN
    assert row is not None  # для типизации: is_frozen уже проверил
    if row.cutover_freeze:
        state = STATE_WINDOW
    elif row.pending_fingerprint:
        state = STATE_BLOCKED
    elif not applying:
        state = STATE_PAUSED
    elif row.last_applied_at is None or now - row.last_applied_at > timedelta(
        seconds=3 * interval_sec
    ):
        state = STATE_STALE
    else:
        state = STATE_SYNCED
    return HrView(
        frozen=True, window=row.cutover_freeze, state=state, synced_at=row.last_applied_at
    )


def tenant_applies(tenant_slug: str | None, apply_slugs: frozenset[str]) -> bool:
    return bool(tenant_slug) and tenant_slug.strip().lower() in apply_slugs


async def load_state(db: AsyncSession, tenant_id: UUID) -> HrSyncState | None:
    """Строка тенанта — по первичному ключу.

    Не `select(HrSyncState)` в надежде на RLS: под сессией без него (bypass,
    миграционная роль, тесты под суперпользователем) такой запрос видит строки
    всех организаций и падает на второй. Это не ручная фильтрация по тенанту —
    строка у организации ровно одна, и RLS по-прежнему стережёт чужую.
    `populate_existing` — всегда из базы: синк пишет строку своими сессиями,
    и объект, закешированный этой сессией раньше, показал бы прошлое состояние.
    """
    return await db.get(HrSyncState, tenant_id, populate_existing=True)


def changed_hr_fields(current: Any, incoming: dict[str, Any]) -> list[str]:
    """Кадровые поля, которые запрос МЕНЯЕТ: форма шлёт объект целиком, и
    старые бандлы тоже — отказывать на «пришло» значило бы сломать сохранение
    телефона и прав у всех."""
    return [
        name
        for name in HR_PROFILE_FIELDS
        if name in incoming and incoming[name] != getattr(current, name)
    ]


# --- Здоровье для алертов (`/api/health/hr` → scripts/healthcheck.sh) -----------

HEALTH_BLOCKED_AFTER = timedelta(hours=1)
HEALTH_PAUSED_AFTER = timedelta(hours=1)
HEALTH_STALE_AFTER = timedelta(hours=1)
HEALTH_WINDOW_AFTER = timedelta(hours=6)


def health_problems(row: HrSyncState, *, applying: bool, now: datetime) -> list[str]:
    """Коды проблем организации — без названий и чисел (ручка анонимная).

    - `window_open` — окно каткатa открыто дольше 6 часов: его забыли закрыть,
      а правка кадров в Hub всё это время закрыта;
    - `blocked` — предохранитель держит изменения дольше часа;
    - `paused` — организация заморожена, но применение для неё не включено
      дольше часа: правки из auth в Hub не приходят, а в Hub их не сделать;
    - `stale` — применение включено, но успешного прогона не было больше часа.
    """
    problems: list[str] = []
    if (
        row.cutover_freeze
        and row.cutover_since is not None
        and now - row.cutover_since > HEALTH_WINDOW_AFTER
    ):
        problems.append("window_open")
    if (
        row.pending_fingerprint
        and row.pending_since is not None
        and now - row.pending_since > HEALTH_BLOCKED_AFTER
    ):
        problems.append("blocked")
    if row.authoritative and not row.cutover_freeze:
        since = row.authoritative_since
        if not applying:
            if since is None or now - since > HEALTH_PAUSED_AFTER:
                problems.append("paused")
        else:
            ref = row.last_applied_at or since
            if ref is None or now - ref > HEALTH_STALE_AFTER:
                problems.append("stale")
    return problems
