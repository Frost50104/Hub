"""Staff-sync (0052): pull штата продукта из auth — «auth — источник штата».

Зачем: Hub узнавал о людях только реактивно (тень на входе, deletion-фид) —
список «кто заведён в auth и с какой hub-ролью» в продукт не приезжал никогда,
и админы не могли ответить «кто добавлен». Pull закрывает дыру целиком:
учётка с hub-ролью появляется в Hub СРАЗУ после выдачи роли в auth, не
дожидаясь первого входа.

Канал — сервисная ручка auth `GET /api/products/employees?product=hub`
(контракт — docs/handoffs/HUB_TASK_staff_endpoint_REPLY.md), ключ СВОЙ
(`staff_service_key`, метка hub) — не общий сервисный. ВАЖНО про контракты:
- «фид никогда не создаёт записи о людях» — про deletion-ФИД; pull-bootstrap
  — другой канал (ровно как /api/products/tenants), INSERT теней здесь легален;
- 404/401/403 от auth = ручки или доступа пока нет → тихий no-op;
- парсер обязан переживать отсутствие любых полей (контракт аддитивный);
- удалённых сотрудников ручка НЕ отдаёт (отказ auth: ручка отдаёт состояние,
  а не события — про удаления сообщает deletion-фид), suspended-организации
  исключены; из цикла пагинации выходим ТОЛЬКО по `next_after == null` —
  страница добивается через границу фаз (сотрудники → приглашения), и
  «короче лимита» концом не является.

Что делает один прогон:
1. upsert `shadow_users` (+ кеш `hub_role`/`auth_active`/`staff_synced_at`) —
   для ВСЕХ строк, включая сервисные учётки;
2. учебная карточка — ТОЛЬКО `account_kind == "person"` с ролью и
   `is_active is True` (требования 1–2 auth: сервисные учётки — точки-кафе
   с адресом в поле имени, карточка им раздала бы неотзываемую рассылку
   обязательных курсов; деактивированный — закрытый вход при живой учётке);
3. replace-снапшот `auth_invitations` по тенанту;
4. гашение `hub_role` у теней тенанта, не пришедших в этом прогоне
   (требование 4: событий об отзыве роли в фиде нет — человек без роли
   просто исчезает из выгрузки). Безопасно: доступ гейтится ролью из JWT,
   кеш — только чип в списке. Поэтому же гашение запрещено на ЧАСТИЧНОМ
   снимке — обрыв пагинации отдаёт None, а не собранный кусок.

`dry_run=True` — подсчёт без единой записи (и без пушей: классификация
read-only, см. `classify_staff_row`). Строки несут ПДн (ФИО/email) — в логи
только счётчики и id.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.employee_profile import EmployeeProfile
from app.models.shadow import AuthInvitation, ShadowUser
from app.services.employee_profiles import (
    archive_profile,
    classify_staff_row,
    ensure_profile_for_staff_row,
    normalize_account_kind,
)

log = structlog.get_logger("staff_sync")

_PAGE_LIMIT = 200
# Предел пагинации (требование 6 auth): если курсор перестанет строго
# возрастать, while без предела превратился бы в горячий HTTP-цикл по auth
# (один процесс без rate-limit на этих путях). 200 страниц × 200 строк —
# на порядки больше реального штата.
_MAX_PAGES = 200


@dataclass
class StaffSyncReport:
    """Счётчики прогона — их возвращает ручной триггер (админ видит масштаб)."""

    available: bool = True
    dry_run: bool = False
    shadows_upserted: int = 0
    profiles_created: int = 0
    profiles_linked: int = 0
    email_conflicts: int = 0
    archived_skips: int = 0
    service_accounts: int = 0
    inactive_skipped: int = 0
    roles_cleared: int = 0
    archived: int = 0
    invitations: int = 0
    tenants: set[str] = field(default_factory=set)


async def _fetch_staff_pages() -> list[dict[str, Any]] | None:
    """Все строки штата из auth; None = снимка нет (нет доступа/сеть/обрыв).

    Отдельная функция — единственная точка HTTP: тесты подменяют её целиком,
    не поднимая транспорт (respx в зависимостях нет). Частичный снимок НЕ
    возвращается никогда — на нём нельзя гасить роли (см. докстринг модуля).
    """
    settings = get_settings()
    if not settings.staff_service_key:
        log.warning("staff_sync.no_service_key")
        return None
    items: list[dict[str, Any]] = []
    after: str | None = None
    try:
        async with httpx.AsyncClient(
            base_url=settings.signaris_auth_base_url,
            headers={"X-Service-Key": settings.staff_service_key},
            timeout=20.0,
        ) as client:
            for _ in range(_MAX_PAGES):
                params: dict[str, Any] = {"product": "hub", "limit": _PAGE_LIMIT}
                if after:
                    params["after"] = after
                resp = await client.get("/api/products/employees", params=params)
                if resp.status_code in (404, 401, 403):
                    # 404 — ручки нет; 401/403 — «доступа пока нет» (не тот
                    # ключ / нет скоупа). Всё это ожидаемая деградация, а не
                    # сбой — INFO, без WARNING-шторма раз в 15 минут.
                    log.info("staff_sync.unavailable", status=resp.status_code)
                    return None
                resp.raise_for_status()
                data = resp.json()
                items.extend(data.get("items") or [])
                after = data.get("next_after")
                if not after:
                    return items
            log.error("staff_sync.pagination_overflow", pages=_MAX_PAGES)
            return None
    except httpx.HTTPStatusError as exc:
        log.warning("staff_sync.fetch_failed", status=exc.response.status_code)
        return None
    except httpx.HTTPError as exc:
        log.warning("staff_sync.fetch_failed", error=type(exc).__name__)
        return None


def _rows_by_tenant(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_tenant: dict[str, list[dict[str, Any]]] = {}
    for row in items:
        tenant_id = row.get("tenant_id")
        if tenant_id:
            by_tenant.setdefault(str(tenant_id), []).append(row)
    return by_tenant


async def sync_staff(*, dry_run: bool = False) -> StaffSyncReport:
    """Один прогон синка по всем тенантам из ответа auth.

    `dry_run=True` — тот же fetch и та же классификация, но ни одной записи
    в БД и ни одного пуша: счётчики показывают, что СДЕЛАЛ БЫ живой прогон.
    """
    report = StaffSyncReport(dry_run=dry_run)
    items = await _fetch_staff_pages()
    if items is None:
        report.available = False
        return report

    now = datetime.now(UTC)
    for tenant_id, rows in _rows_by_tenant(items).items():
        report.tenants.add(tenant_id)
        async with tenant_scoped_session(UUID(tenant_id)) as db:
            await _apply_tenant(db, UUID(tenant_id), rows, now, report, dry_run=dry_run)
            if not dry_run:
                await db.commit()
    log.info(
        "staff_sync.done",
        dry_run=dry_run,
        tenants=len(report.tenants),
        shadows=report.shadows_upserted,
        created=report.profiles_created,
        linked=report.profiles_linked,
        conflicts=report.email_conflicts,
        archived_skips=report.archived_skips,
        service_accounts=report.service_accounts,
        inactive_skipped=report.inactive_skipped,
        roles_cleared=report.roles_cleared,
        archived=report.archived,
        invitations=report.invitations,
    )
    return report


async def _apply_tenant(
    db,  # noqa: ANN001 — AsyncSession
    tenant_id: UUID,
    rows: list[dict[str, Any]],
    now: datetime,
    report: StaffSyncReport,
    *,
    dry_run: bool,
) -> None:
    invitations: list[dict[str, Any]] = []
    for row in rows:
        if row.get("kind") == "invitation":
            invitations.append(row)
            continue
        employee_id = row.get("employee_id")
        email = row.get("email")
        if not employee_id or not email:
            continue
        employee_uuid = UUID(str(employee_id))
        full_name = (row.get("full_name") or "").strip()
        role = row.get("role")
        deleted_raw = row.get("deleted_at")
        is_active = row.get("is_active")
        # Дефолт "person" сознательно: контракт аддитивный, поле auth не
        # уберёт; строже гейтит is_active ниже.
        #
        # Нормализация обязательна и вот почему: до неё любое значение уезжало
        # в карточку как есть, а там CHECK IN ('person','service') — третий вид
        # из auth уронил бы IntegrityError'ом ВЕСЬ прогон, каждые 15 минут, до
        # выката (замечание auth 16.09). Незнакомое значение при этом не
        # теряется молча: пишем WARNING, чтобы узнать о расширении контракта
        # из журнала, а не по сломанному синку.
        raw_kind = row.get("account_kind")
        account_kind = normalize_account_kind(raw_kind)
        if raw_kind is not None and raw_kind != account_kind:
            log.warning("staff_sync.unknown_account_kind", raw=raw_kind, stored=account_kind)

        # Тень: INSERT новых легален (pull-bootstrap, не фид) и положен ВСЕМ,
        # включая сервисные учётки. Непустое имя из pull не перетирается
        # пустым (правило _sync_linked_profile).
        report.shadows_upserted += 1
        if not dry_run:
            stmt = pg_insert(ShadowUser).values(
                employee_id=employee_uuid,
                tenant_id=tenant_id,
                email=email,
                full_name=full_name or email,
                hub_role=role,
                auth_active=bool(is_active) if is_active is not None else None,
                account_kind=account_kind,
                staff_synced_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["employee_id"],
                set_={
                    "tenant_id": tenant_id,
                    "email": email,
                    "full_name": stmt.excluded.full_name,
                    "hub_role": role,
                    "auth_active": stmt.excluded.auth_active,
                    "account_kind": account_kind,
                    "staff_synced_at": now,
                },
            )
            await db.execute(stmt)

        if deleted_raw:
            # Ручка удалённых не отдаёт (отказ auth), ветка — толерантность к
            # будущему контракту: та же реакция, что у deletion-sync.
            if dry_run:
                report.archived += 1
                continue
            shadow = await db.get(ShadowUser, employee_uuid)
            if shadow is not None and shadow.deleted_at is None:
                shadow.deleted_at = now
            profile = (
                await db.execute(
                    select(EmployeeProfile).where(
                        EmployeeProfile.employee_id == employee_uuid,
                        EmployeeProfile.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if profile is not None:
                await archive_profile(db, profile, reason="auth_deleted", actor_id=None)
                report.archived += 1
            continue

        # Учебная карточка — только людям (требование 1: сервисной учётке
        # карточка раздала бы неотзываемую рассылку обязательных курсов) с
        # открытым входом (требование 2; is_active is True — fail-closed:
        # если поле пропадёт из контракта, создание встанет ВИДИМО по
        # счётчику created=0, а не тихо раздаст карточки).
        if account_kind != "person":
            # Карточки точек-кафе остаются (решение владельца 04.09: на кассе
            # точки открыт её аккаунт), поэтому СУЩЕСТВУЮЩУЮ карточку
            # привязываем — непривязанная показывала «без учётки» при живой
            # учётке в auth. Создание по-прежнему закрыто (link_only).
            report.service_accounts += 1
            if dry_run:
                outcome = await classify_staff_row(
                    db, employee_id=employee_uuid, email=email, link_only=True
                )
            else:
                outcome = await ensure_profile_for_staff_row(
                    db,
                    tenant_id=tenant_id,
                    employee_id=employee_uuid,
                    email=email,
                    full_name=full_name,
                    link_only=True,
                    account_kind=account_kind,
                )
            if outcome == "linked":
                report.profiles_linked += 1
            elif outcome == "email_conflict":
                report.email_conflicts += 1
            continue
        if not role:
            continue
        if is_active is not True:
            report.inactive_skipped += 1
            continue
        if dry_run:
            outcome = await classify_staff_row(db, employee_id=employee_uuid, email=email)
        else:
            outcome = await ensure_profile_for_staff_row(
                db,
                tenant_id=tenant_id,
                employee_id=employee_uuid,
                email=email,
                full_name=full_name,
                account_kind=account_kind,
            )
        if outcome == "created":
            report.profiles_created += 1
        elif outcome == "linked":
            report.profiles_linked += 1
        elif outcome == "email_conflict":
            report.email_conflicts += 1
        elif outcome == "archived_skip":
            report.archived_skips += 1

    # Приглашения — снапшот целиком: принятые/отозванные исчезают сами.
    if not dry_run:
        await db.execute(delete(AuthInvitation).where(AuthInvitation.tenant_id == tenant_id))
    for inv in invitations:
        inv_id = inv.get("invitation_id")
        email = inv.get("email")
        if not inv_id or not email:
            continue
        report.invitations += 1
        if dry_run:
            continue
        db.add(
            AuthInvitation(
                id=UUID(str(inv_id)),
                tenant_id=tenant_id,
                email=email,
                full_name=(inv.get("full_name") or None),
                role=inv.get("role") or "member",
                expires_at=_parse_dt(inv.get("invited_expires_at")),
                synced_at=now,
            )
        )

    # Гашение ролей (требование 4): кто не пришёл в ЭТОМ прогоне — роли в
    # auth больше нет. Строки прогона не задеваются: их staff_synced_at ==
    # now (тот же объект datetime), сравнение строго «<»; NULL — роль есть,
    # синка не было (залипший кеш) — тоже гасим. Только на ПОЛНОМ снимке
    # (обрыв пагинации отдаёт None выше) и никогда в dry-run.
    if not dry_run:
        # Тенант скоупит RLS самой сессии — ручной WHERE tenant_id запрещён.
        result = await db.execute(
            update(ShadowUser)
            .where(
                ShadowUser.hub_role.is_not(None),
                or_(
                    ShadowUser.staff_synced_at.is_(None),
                    ShadowUser.staff_synced_at < now,
                ),
            )
            .values(hub_role=None)
        )
        report.roles_cleared += result.rowcount


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def start_worker() -> None:
    """Периодический прогон; вызывается под supervise + leader-lock."""
    settings = get_settings()
    while True:
        try:
            await sync_staff()
        except Exception:  # noqa: BLE001 — воркер не должен умирать от одного сбоя
            log.exception("staff_sync.tick_failed")
        await asyncio.sleep(settings.staff_sync_interval_sec)
