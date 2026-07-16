"""HR-профили: матчинг с auth-аккаунтом, архивация, восстановление (Ф0 LMS).

Матчинг (вызывается из /api/me ТОЛЬКО для principals с hub-ролью — иначе
юзеры других продуктов Signaris засоряли бы оргструктуру):
1. профиль уже привязан по employee_id → синк email при расхождении;
2. активный профиль с тем же lower(email) без привязки → привязать;
3. АРХИВНЫЙ профиль с тем же email (повторный найм) → НЕ создавать дубль,
   вернуть needs_restore — админ восстанавливает через re-link;
4. ничего → создать минимальный профиль (email+ФИО из JWT), HR дозаполнит.

Гонка первого входа гасится partial-unique (tenant_id, lower(email)) WHERE
status='active' + INSERT ON CONFLICT DO NOTHING + повторный SELECT.

Архивация — единый каскад для увольнения/неактивности/deletion-sync:
статус + вычистка audience_members (+ с Ф5 — cancel automation_jobs).
История обучения не удаляется никогда (ТЗ §23).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import structlog
from signaris_auth import Principal
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_profile import EmployeeProfile
from app.services import audit
from app.services.audience_resolver import recalc_profile

log = structlog.get_logger("employee_profiles")


def normalize_email(email: str) -> str:
    return email.strip().lower()


@dataclass
class MatchResult:
    outcome: Literal["linked", "created", "needs_restore", "already_linked"]
    profile: EmployeeProfile | None


async def _find_by_employee_id(db: AsyncSession, employee_id: UUID) -> EmployeeProfile | None:
    return (
        await db.execute(
            select(EmployeeProfile).where(EmployeeProfile.employee_id == employee_id)
        )
    ).scalar_one_or_none()


async def _find_by_email(
    db: AsyncSession, email: str, *, status: str
) -> EmployeeProfile | None:
    return (
        await db.execute(
            select(EmployeeProfile).where(
                func.lower(EmployeeProfile.email) == normalize_email(email),
                EmployeeProfile.status == status,
            )
        )
    ).scalar_one_or_none()


async def ensure_profile_for_principal(db: AsyncSession, principal: Principal) -> MatchResult:
    """Идемпотентный матчинг/создание профиля. Коммитит вызывающий."""
    now = datetime.now(UTC)

    existing = await _find_by_employee_id(db, principal.employee_id)
    if existing is not None:
        await _sync_linked_profile(db, existing, principal, now)
        return MatchResult(outcome="already_linked", profile=existing)

    email = normalize_email(principal.email)

    active = await _find_by_email(db, email, status="active")
    if active is not None:
        if active.employee_id is None:
            # Guard в WHERE — параллельный запрос не перепривяжет чужой профиль.
            result = await db.execute(
                update(EmployeeProfile)
                .where(EmployeeProfile.id == active.id, EmployeeProfile.employee_id.is_(None))
                .values(employee_id=principal.employee_id, last_activity_at=now)
            )
            if result.rowcount:
                log.info("profile.linked", profile_id=str(active.id))
                await db.refresh(active)
                await recalc_profile(db, active)
                return MatchResult(outcome="linked", profile=active)
            existing = await _find_by_employee_id(db, principal.employee_id)
            return MatchResult(outcome="already_linked", profile=existing)
        # Активный профиль с этим email принадлежит другому auth-аккаунту —
        # в auth email уникален, значит это рассинхрон данных. Не трогаем.
        log.warning(
            "profile.email_conflict",
            email=email,
            profile_id=str(active.id),
        )
        return MatchResult(outcome="needs_restore", profile=None)

    archived = await _find_by_email(db, email, status="archived")
    if archived is not None:
        # Повторный найм: история на архивной карточке, дубль не создаём.
        log.info("profile.needs_restore", profile_id=str(archived.id), email=email)
        return MatchResult(outcome="needs_restore", profile=archived)

    stmt = (
        pg_insert(EmployeeProfile)
        .values(
            tenant_id=principal.tenant_id,
            employee_id=principal.employee_id,
            email=email,
            full_name=principal.full_name,
            last_activity_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", func.lower(EmployeeProfile.email)],
            index_where=EmployeeProfile.status == "active",
        )
        .returning(EmployeeProfile.id)
    )
    inserted_id = (await db.execute(stmt)).scalar_one_or_none()
    if inserted_id is None:
        # Гонка: параллельный запрос успел первым — читаем его результат.
        profile = await _find_by_email(db, email, status="active")
        return MatchResult(outcome="already_linked", profile=profile)
    profile = (
        await db.execute(select(EmployeeProfile).where(EmployeeProfile.id == inserted_id))
    ).scalar_one()
    log.info("profile.autocreated", profile_id=str(inserted_id), email=email)
    return MatchResult(outcome="created", profile=profile)


async def _sync_linked_profile(
    db: AsyncSession,
    profile: EmployeeProfile,
    principal: Principal,
    now: datetime,
) -> None:
    values: dict = {"last_activity_at": now}
    new_email = normalize_email(principal.email)
    if normalize_email(profile.email) != new_email:
        # Смена email в auth. Pre-check вместо ловли IntegrityError — ошибка
        # уникальности убила бы всю транзакцию запроса.
        holder = await _find_by_email(db, new_email, status="active")
        if holder is None or holder.id == profile.id:
            audit.record(
                db,
                tenant_id=profile.tenant_id,
                actor_id=principal.employee_id,
                action="update",
                object_type="employee_profile",
                object_id=profile.id,
                object_label=profile.full_name,
                diff={"email": {"old": profile.email, "new": new_email}},
            )
            values["email"] = new_email
        else:
            log.warning(
                "profile.email_sync_conflict",
                profile_id=str(profile.id),
                new_email=new_email,
                holder_id=str(holder.id),
            )
    await db.execute(
        update(EmployeeProfile).where(EmployeeProfile.id == profile.id).values(**values)
    )


async def archive_profile(
    db: AsyncSession,
    profile: EmployeeProfile,
    *,
    reason: str,
    actor_id: UUID | None,
) -> None:
    """Единый каскад архивации. Идемпотентен (уже архивный → no-op)."""
    if profile.status == "archived":
        return
    profile.status = "archived"
    profile.archived_at = datetime.now(UTC)
    profile.archive_reason = reason
    await db.flush()
    # Каскад: членства аудиторий (recalc_profile для archived удаляет все).
    await recalc_profile(db, profile)
    # TODO(Ф5): cancel pending automation_jobs профиля.
    audit.record(
        db,
        tenant_id=profile.tenant_id,
        actor_id=actor_id,
        action="archive",
        object_type="employee_profile",
        object_id=profile.id,
        object_label=profile.full_name,
        diff={"reason": {"old": None, "new": reason}},
    )
    log.info("profile.archived", profile_id=str(profile.id), reason=reason)


async def restore_profile(
    db: AsyncSession,
    profile: EmployeeProfile,
    *,
    actor_id: UUID | None,
    new_employee_id: UUID | None = None,
) -> None:
    """Восстановление из архива, опционально с перепривязкой к новому
    auth-аккаунту (повторный найм: в auth у человека новый employee_id)."""
    if profile.status == "active":
        return
    dup = await _find_by_email(db, profile.email, status="active")
    if dup is not None:
        raise ValueError(
            f"Активный профиль с email {profile.email} уже существует — "
            "восстановление создаст дубль."
        )
    if new_employee_id is not None:
        holder = await _find_by_employee_id(db, new_employee_id)
        if holder is not None and holder.id != profile.id:
            raise ValueError("Этот вход уже привязан к другой карточке.")
        profile.employee_id = new_employee_id
    profile.status = "active"
    profile.archived_at = None
    profile.archive_reason = None
    await db.flush()
    await recalc_profile(db, profile)
    audit.record(
        db,
        tenant_id=profile.tenant_id,
        actor_id=actor_id,
        action="restore",
        object_type="employee_profile",
        object_id=profile.id,
        object_label=profile.full_name,
    )
    log.info("profile.restored", profile_id=str(profile.id))
