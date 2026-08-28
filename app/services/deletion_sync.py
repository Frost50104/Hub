"""Deletion-sync consumer — pulls employee/tenant deletions from auth.signaris.ru.

INTEGRATION.md §14. Cursor lives in `sync_state(key='deletion_sync', cursor BIGINT)`.
`on_event` is a no-op for Hub: we keep tasks/comments authored by removed
employees (history matters) and filter `shadow_users.deleted_at IS NULL` at
read time. The worker auto-marks the shadow row as deleted.
"""

from __future__ import annotations

import structlog
from signaris_auth import DeletionEvent
from signaris_auth.sync import run_deletion_sync_worker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import bypass_session_factory, tenant_scoped_session

log = structlog.get_logger("deletion_sync")
_CURSOR_KEY = "deletion_sync"


async def _load_cursor() -> int:
    async with tenant_scoped_session(None, bypass_rls=True) as session:
        row = await session.execute(
            text("SELECT cursor FROM sync_state WHERE key = :k"),
            {"k": _CURSOR_KEY},
        )
        value = row.scalar_one_or_none()
        if value is None:
            await session.execute(
                text(
                    "INSERT INTO sync_state (key, cursor) VALUES (:k, 0) "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {"k": _CURSOR_KEY},
            )
            await session.commit()
            return 0
        return int(value)


async def _save_cursor(seq: int) -> None:
    async with tenant_scoped_session(None, bypass_rls=True) as session:
        await session.execute(
            text(
                "INSERT INTO sync_state (key, cursor) VALUES (:k, :s) "
                "ON CONFLICT (key) DO UPDATE SET cursor = EXCLUDED.cursor"
            ),
            {"k": _CURSOR_KEY, "s": seq},
        )
        await session.commit()


async def _apply_rename(event: DeletionEvent) -> None:
    """`employee_updated`: имя из auth → HR-карточка сотрудника.

    Копий имени в Hub две. `shadow_users.full_name` (её читает весь трекер)
    обновляет сама библиотека сразу после `on_event`; здесь — вторая копия,
    `employee_profiles.full_name`, которую видно на learn-экранах, в
    оргструктуре и в сертификатах. Без этой ветки случай закрывается наполовину.

    Только UPDATE существующей карточки: фид не должен становиться каналом
    создания записей о людях, которые в Hub не приходили. Карточки нет (человек
    не заходил и HR его не заводил) — выходим молча, при первом входе имя
    подтянет `_sync_linked_profile`.

    Ветка идемпотентна (совпало имя — выходим): курсор двигается ПОСЛЕ
    `on_event`, поэтому упавшее событие переиграется на следующем тике. По той
    же причине ошибку БД не глушим — молчаливая потеря переименования хуже
    повтора; так же устроена соседняя ветка с `archive_profile`.
    """
    new_name = (event.full_name or "").strip()
    if not new_name or event.employee_id is None or event.tenant_id is None:
        return

    from sqlalchemy import select

    from app.models.employee_profile import EmployeeProfile
    from app.services import audit

    async with tenant_scoped_session(event.tenant_id) as domain_session:
        profile = (
            await domain_session.execute(
                select(EmployeeProfile).where(
                    EmployeeProfile.employee_id == event.employee_id
                )
            )
        ).scalar_one_or_none()
        if profile is None or profile.full_name == new_name:
            return
        audit.record(
            domain_session,
            tenant_id=profile.tenant_id,
            actor_id=None,  # инициатор — auth, а не человек в Hub
            action="update",
            object_type="employee_profile",
            object_id=profile.id,
            object_label=new_name,
            diff={"full_name": {"old": profile.full_name, "new": new_name}},
        )
        profile.full_name = new_name
        await domain_session.commit()
    # Имя в лог не пишем: ПДн (требование INTEGRATION.md §14).
    log.info("deletion_sync.profile_renamed", seq=event.seq)


async def _on_event(session: AsyncSession, event: DeletionEvent) -> None:
    # Task-домен: no-op (историю задач/комментов сохраняем, read-path фильтрует
    # shadow_users.deleted_at). Learn-домен (Ф0): удаление/перевод сотрудника в
    # auth архивирует его HR-профиль. Доменная запись — в СВОЕЙ tenant-scoped
    # сессии (сессия воркера — только для очереди/shadow, инвариант плана);
    # archive_profile идемпотентен — повторная обработка события безопасна.
    log.info(
        "deletion_sync.event",
        seq=event.seq,
        kind=event.event_type,
        employee_id=str(event.employee_id) if event.employee_id else None,
        tenant_id=str(event.tenant_id) if event.tenant_id else None,
    )
    if event.event_type == "employee_updated":
        await _apply_rename(event)
        return
    if event.event_type not in ("employee_deleted", "employee_transferred"):
        return
    if event.employee_id is None:
        return
    # Для transferred профиль архивируем в СТАРОМ tenant (человек уехал).
    tenant_id = getattr(event, "from_tenant_id", None) or event.tenant_id
    if tenant_id is None:
        return

    from sqlalchemy import select

    from app.models.employee_profile import EmployeeProfile
    from app.services.employee_profiles import archive_profile

    async with tenant_scoped_session(tenant_id) as domain_session:
        profile = (
            await domain_session.execute(
                select(EmployeeProfile).where(
                    EmployeeProfile.employee_id == event.employee_id
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            # Карточка без привязки (человек не заходил) авто-архиву недоступна —
            # HR архивирует вручную через админку.
            return
        await archive_profile(
            domain_session, profile, reason="auth_deleted", actor_id=None
        )
        await domain_session.commit()
        log.info(
            "deletion_sync.profile_archived",
            profile_id=str(profile.id),
            kind=event.event_type,
        )


async def start_worker() -> None:
    settings = get_settings()
    if not settings.signaris_service_key:
        log.warning("deletion_sync.no_service_key")
        return
    # bypass-фабрика: воркер lib'ы пишет в FORCE-RLS shadow_users сам —
    # сырая фабрика без RLS-маркера молча обновляла бы 0 строк.
    await run_deletion_sync_worker(
        bypass_session_factory(),
        base_url=settings.signaris_auth_base_url,
        service_key=settings.signaris_service_key,
        on_event=_on_event,
        load_cursor=_load_cursor,
        save_cursor=_save_cursor,
        poll_sec=settings.deletion_sync_poll_sec,
        shadow_table="shadow_users",
    )
