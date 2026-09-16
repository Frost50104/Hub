"""Статус учётной записи для карточки сотрудника — ОДИН расчёт (16.09).

До этого он считался дважды одинаковым кодом: в `api/employees.py::_to_responses`
(экран «Сотрудники») и в `services/learning_progress.py::_auth_states` (экран
«Прогресс» и CSV-выгрузка), причём сервис импортировал функцию из слоя API.
Две копии — два места, где новое состояние можно забыть; статус «Приглашён(а)»
здесь и появился, поэтому расчёт переехал в один сервис, а `api/employees.py`
лишь реэкспортирует имена (юнит-тест `test_staff_snapshot_fresh` и внешние
импорты не меняются).

Источники — зеркала auth, которые пишет staff-sync (0052): `shadow_users`
(учётка, роль, активность) и `auth_invitations` (непринятые приглашения,
снапшот). Ручного `WHERE tenant_id` здесь нет: сессия запроса RLS-скоуплена,
и все вызовы идут из ручек (джоб-вызовов нет).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.employee_profile import EmployeeProfile
from app.models.shadow import AuthInvitation, ShadowUser
from app.services.employee_profiles import normalize_email


def staff_snapshot_fresh(
    last_synced_at: datetime | None, *, now: datetime, interval_sec: float
) -> bool:
    """Снимок auth живой = не старше двух интервалов воркера (совет auth).

    «Был хоть один синк» — залипающий флаг: сломайся ключ, экран неделю
    уверенно писал бы «без учётки» по устаревшему снимку. Протухший снимок
    откатывает статусы к осторожному «не привязан(а)»."""
    if last_synced_at is None:
        return False
    return (now - last_synced_at).total_seconds() <= 2 * interval_sec


def auth_state_for(
    *,
    employee_id: UUID | None,
    last_activity_at: object,
    shadow_deleted: bool,
    auth_active: bool | None,
    staff_synced: bool,
    invited: bool = False,
) -> str:
    """Честный статус учётки для карточки — ОДНА функция вместо двух
    рассинхронённых признаков в JSX (бейдж считался по employee_id, заморозка
    по last_activity_at — восстановленная карточка показывалась «не входил»
    с замороженными полями).

    До первого staff-sync утверждать «без учётки» нельзя: непривязанная
    карточка может принадлежать человеку с живой учёткой, который просто не
    входил, — до синка отдаём осторожное `not_linked`.

    `invited` (16.09) — почта карточки есть среди непринятых приглашений auth.
    Значимо только на свежем снимке: приглашение живёт 7 дней, и по протухшему
    зеркалу уверенно говорить «приглашён(а)» так же нельзя, как «без учётки».
    """
    if employee_id is None:
        if not staff_synced:
            return "not_linked"
        return "invited" if invited else "no_account"
    if shadow_deleted:
        return "deleted"
    if auth_active is False:
        return "blocked"
    if last_activity_at is None:
        return "not_logged_in"
    return "active"


@dataclass(frozen=True)
class AuthStateInfo:
    hub_role: str | None
    state: str


async def auth_states_for_profiles(
    db: AsyncSession, profiles: list[EmployeeProfile]
) -> dict[UUID, AuthStateInfo]:
    """Роль и статус учётки для списка карточек — три запроса на страницу.

    Приглашения читаются только когда снимок свежий И среди карточек есть
    непривязанные: у привязанной карточки приглашение ничего не значит
    (`auth_state_for` смотрит `employee_id` первым), а на протухшем снимке
    оно не учитывается.
    """
    settings = get_settings()
    staff_synced = staff_snapshot_fresh(
        (await db.execute(select(func.max(ShadowUser.staff_synced_at)))).scalar_one_or_none(),
        now=datetime.now(UTC),
        interval_sec=settings.staff_sync_interval_sec,
    )
    employee_ids = [p.employee_id for p in profiles if p.employee_id is not None]
    shadows: dict[UUID, tuple[str | None, bool, bool | None]] = {}
    if employee_ids:
        for eid, hub_role, deleted_at, auth_active in await db.execute(
            select(
                ShadowUser.employee_id,
                ShadowUser.hub_role,
                ShadowUser.deleted_at,
                ShadowUser.auth_active,
            ).where(ShadowUser.employee_id.in_(employee_ids))
        ):
            shadows[eid] = (hub_role, deleted_at is not None, auth_active)
    invited_emails: set[str] = set()
    if staff_synced and any(p.employee_id is None for p in profiles):
        invited_emails = {
            row[0] for row in await db.execute(select(func.lower(AuthInvitation.email)))
        }
    out: dict[UUID, AuthStateInfo] = {}
    for p in profiles:
        hub_role, shadow_deleted, auth_active = (
            shadows.get(p.employee_id, (None, False, None))
            if p.employee_id
            else (None, False, None)
        )
        out[p.id] = AuthStateInfo(
            hub_role=hub_role,
            state=auth_state_for(
                employee_id=p.employee_id,
                last_activity_at=p.last_activity_at,
                shadow_deleted=shadow_deleted,
                auth_active=auth_active,
                staff_synced=staff_synced,
                invited=normalize_email(p.email) in invited_emails,
            ),
        )
    return out
