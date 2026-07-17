"""Библиотека знаний API (Ф1, ТЗ §8): разделы, материалы, версии, ознакомления.

Permissions:
- чтение — любой hub-юзер: published-материалы, отфильтрованные audience
  (и своей, и раздела); author дополнительно видит СВОИ черновики,
  publisher/hub:admin — всё;
- создание/правка — content_role author+ (author — только своё),
  публикация/архив/аудитория/разделы — publisher+;
- отчёт об ознакомлении — publisher/admin (все) или ТУ/франчайзи
  (строки своих магазинов через org_scope).

Ack-инварианты (adversarial-ревью): подтверждается ВЕРСИЯ, которую отдал
сервер; кнопка гейтится фактом открытия (view_history); дедлайн — от
max(published_at, granted_at).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from signaris_auth import Principal
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.audience import AudienceMember
from app.models.employee_profile import EmployeeProfile
from app.models.library import (
    LibraryMaterial,
    LibrarySection,
    MaterialAcknowledgement,
    MaterialVersion,
    ViewHistory,
)
from app.models.search_document import TextExtractionJob
from app.models.shadow import ShadowUser
from app.schemas.library import (
    AckBody,
    AckReportResponse,
    AckReportRow,
    AudienceBody,
    LibraryResponse,
    MaterialCreate,
    MaterialResponse,
    MaterialUpdate,
    SectionCreate,
    SectionResponse,
    SectionUpdate,
    StatusBody,
    VersionResponse,
)
from app.services import audit, lifecycle
from app.services.audience_resolver import (
    RuleSpec,
    set_object_audience,
    visible_filter,
)
from app.services.content_access import require_content_role, resolve_content_role
from app.services.learn_notify import notify_ack_required
from app.services.library_storage import (
    LIBRARY_MIME,
    absolute_path,
    storage_key_for_version,
)
from app.services.org_scope import get_profile, resolve_scope
from app.services.search_indexer import delete_document, upsert_document

router = APIRouter(tags=["learn-library"])

_OBJECT_TYPE = "library_material"


def _rule_specs(body: AudienceBody) -> list[RuleSpec]:
    return [
        RuleSpec(
            mode=r.mode,
            profile_ids=frozenset(r.profile_ids),
            position_ids=frozenset(r.position_ids),
            position_group_ids=frozenset(r.position_group_ids),
            store_ids=frozenset(r.store_ids),
            store_group_ids=frozenset(r.store_group_ids),
            franchisee_ids=frozenset(r.franchisee_ids),
            franchisee_group_ids=frozenset(r.franchisee_group_ids),
            department_ids=frozenset(r.department_ids),
            user_group_ids=frozenset(r.user_group_ids),
        )
        for r in body.rules
    ]


def _effective_ack_version(material: LibraryMaterial) -> int:
    """Версия, которую нужно подтверждать: файл → current, ссылка → 0."""
    return material.current_version_no or 0


async def _get_material_or_404(db: AsyncSession, material_id: UUID) -> LibraryMaterial:
    material = await db.get(LibraryMaterial, material_id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Материал не найден")
    return material


def _require_manage(
    material: LibraryMaterial, principal: Principal, role: lifecycle.ContentRole
) -> None:
    """Author управляет только своим; publisher/admin — всем."""
    if lifecycle.can(role, "publisher"):
        return
    if role == "author" and material.created_by == principal.employee_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Это не ваш материал"
    )


async def _is_member(db: AsyncSession, audience_id: UUID | None, profile_id: UUID | None) -> bool:
    if audience_id is None:
        return True
    if profile_id is None:
        return False
    row = await db.execute(
        select(AudienceMember.profile_id).where(
            AudienceMember.audience_id == audience_id,
            AudienceMember.profile_id == profile_id,
        )
    )
    return row.scalar_one_or_none() is not None


async def _material_visible_to(
    db: AsyncSession,
    material: LibraryMaterial,
    principal: Principal,
    role: lifecycle.ContentRole,
    profile_id: UUID | None,
) -> bool:
    if lifecycle.can(role, "publisher"):
        return True
    if role == "author" and material.created_by == principal.employee_id:
        return True
    if material.status != "published":
        return False
    if not await _is_member(db, material.audience_id, profile_id):
        return False
    if material.section_id is not None:
        section = await db.get(LibrarySection, material.section_id)
        if section is not None and not await _is_member(db, section.audience_id, profile_id):
            return False
    return True


async def _reindex(db: AsyncSession, material: LibraryMaterial) -> None:
    if material.status == "published":
        await upsert_document(
            db,
            tenant_id=material.tenant_id,
            object_type=_OBJECT_TYPE,
            object_id=material.id,
            title=material.title,
            snippet=material.description,
            audience_id=material.audience_id,
            published_at=material.published_at,
            url_path=f"/learn/library?m={material.id}",
        )
    else:
        await delete_document(db, object_type=_OBJECT_TYPE, object_id=material.id)


async def _track_open(
    db: AsyncSession, *, tenant_id: UUID, profile_id: UUID, material_id: UUID
) -> None:
    stmt = pg_insert(ViewHistory).values(
        profile_id=profile_id,
        object_type=_OBJECT_TYPE,
        object_id=material_id,
        tenant_id=tenant_id,
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["profile_id", "object_type", "object_id"],
            set_={
                "last_viewed_at": text("now()"),
                "view_count": ViewHistory.view_count + 1,
            },
        )
    )


async def _audience_profile_ids(
    db: AsyncSession, audience_id: UUID | None
) -> list[UUID]:
    """Члены аудитории; NULL = все активные профили."""
    if audience_id is None:
        rows = await db.execute(
            select(EmployeeProfile.id).where(EmployeeProfile.status == "active")
        )
    else:
        rows = await db.execute(
            select(AudienceMember.profile_id).where(
                AudienceMember.audience_id == audience_id
            )
        )
    return [r[0] for r in rows]


async def _not_acked(
    db: AsyncSession, material: LibraryMaterial, profile_ids: list[UUID]
) -> list[UUID]:
    if not profile_ids:
        return []
    effective = _effective_ack_version(material)
    stmt = select(MaterialAcknowledgement.profile_id).where(
        MaterialAcknowledgement.material_id == material.id,
        MaterialAcknowledgement.profile_id.in_(profile_ids),
    )
    if material.re_ack_on_new_version:
        stmt = stmt.where(MaterialAcknowledgement.version_no == effective)
    acked = {r[0] for r in await db.execute(stmt)}
    return [pid for pid in profile_ids if pid not in acked]


# --- Основной список ---------------------------------------------------------


@router.get("/learn/library", response_model=LibraryResponse)
async def get_library(
    manage: bool = Query(default=False),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> LibraryResponse:
    role = await resolve_content_role(db, principal)
    profile = await get_profile(db, principal)
    profile_id = profile.id if profile is not None else None

    # Разделы: в manage-режиме publisher видит все, иначе — только видимые.
    sections_stmt = select(LibrarySection).order_by(
        LibrarySection.position, LibrarySection.title
    )
    if not (manage and lifecycle.can(role, "publisher")):
        sections_stmt = sections_stmt.where(
            visible_filter(LibrarySection, profile_id or UUID(int=0))
        )
    sections = (await db.execute(sections_stmt)).scalars().all()
    visible_section_ids = {s.id for s in sections}

    # Материалы.
    if manage and lifecycle.can(role, "publisher"):
        materials_stmt = select(LibraryMaterial)
    elif manage and role == "author":
        materials_stmt = select(LibraryMaterial).where(
            (LibraryMaterial.created_by == principal.employee_id)
            | (
                (LibraryMaterial.status == "published")
                & visible_filter(LibraryMaterial, profile_id or UUID(int=0))
            )
        )
    else:
        materials_stmt = select(LibraryMaterial).where(
            LibraryMaterial.status == "published",
            visible_filter(LibraryMaterial, profile_id or UUID(int=0)),
        )
    materials = list(
        (await db.execute(materials_stmt.order_by(LibraryMaterial.title))).scalars().all()
    )
    if not (manage and lifecycle.can(role, "publisher")):
        # Материал в невидимом разделе скрывается (доступ на раздел, ТЗ §18).
        materials = [
            m for m in materials if m.section_id is None or m.section_id in visible_section_ids
        ]

    material_ids = [m.id for m in materials]

    # Персональные флаги и данные версий — bulk, без N+1.
    opened: set[UUID] = set()
    acks: dict[UUID, set[int]] = {}
    if profile_id and material_ids:
        opened = {
            r[0]
            for r in await db.execute(
                select(ViewHistory.object_id).where(
                    ViewHistory.profile_id == profile_id,
                    ViewHistory.object_type == _OBJECT_TYPE,
                    ViewHistory.object_id.in_(material_ids),
                )
            )
        }
        for mid, ver in await db.execute(
            select(
                MaterialAcknowledgement.material_id, MaterialAcknowledgement.version_no
            ).where(
                MaterialAcknowledgement.profile_id == profile_id,
                MaterialAcknowledgement.material_id.in_(material_ids),
            )
        ):
            acks.setdefault(mid, set()).add(ver)

    versions: dict[tuple[UUID, int], MaterialVersion] = {}
    if material_ids:
        for v in (
            (
                await db.execute(
                    select(MaterialVersion).where(
                        MaterialVersion.material_id.in_(material_ids)
                    )
                )
            )
            .scalars()
            .all()
        ):
            versions[(v.material_id, v.version_no)] = v

    owner_ids = {m.owner_id for m in materials if m.owner_id}
    owner_names: dict[UUID, str] = {}
    if owner_ids:
        owner_names = {
            r[0]: r[1]
            for r in await db.execute(
                select(ShadowUser.employee_id, ShadowUser.full_name).where(
                    ShadowUser.employee_id.in_(owner_ids)
                )
            )
        }

    out = []
    for m in materials:
        resp = MaterialResponse.model_validate(m)
        resp.owner_name = owner_names.get(m.owner_id) if m.owner_id else None
        if m.current_version_no is not None:
            v = versions.get((m.id, m.current_version_no))
            if v is not None:
                resp.current_version = VersionResponse.model_validate(v)
        resp.opened_by_me = m.id in opened
        my_acks = acks.get(m.id, set())
        if m.re_ack_on_new_version:
            resp.acked_by_me = _effective_ack_version(m) in my_acks
        else:
            resp.acked_by_me = bool(my_acks)
        resp.ack_pending = (
            m.requires_acknowledgement and m.status == "published" and not resp.acked_by_me
        )
        out.append(resp)

    return LibraryResponse(
        sections=[SectionResponse.model_validate(s) for s in sections],
        materials=out,
        content_role=role,
    )


# --- Разделы -----------------------------------------------------------------


@router.post("/learn/library/sections", response_model=SectionResponse, status_code=201)
async def create_section(
    body: SectionCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SectionResponse:
    await require_content_role(db, principal, "publisher")
    section = LibrarySection(
        tenant_id=principal.tenant_id, title=body.title, parent_id=body.parent_id
    )
    db.add(section)
    await db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type="library_section",
        object_id=section.id,
        object_label=section.title,
    )
    await db.commit()
    await db.refresh(section)
    return SectionResponse.model_validate(section)


@router.patch("/learn/library/sections/{section_id}", response_model=SectionResponse)
async def update_section(
    section_id: UUID,
    body: SectionUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> SectionResponse:
    await require_content_role(db, principal, "publisher")
    section = await db.get(LibrarySection, section_id)
    if section is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Раздел не найден")
    if body.parent_id == section_id:
        raise HTTPException(status_code=422, detail="Раздел не может быть вложен в себя")
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(section, name, value)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="library_section",
        object_id=section.id,
        object_label=section.title,
    )
    await db.commit()
    await db.refresh(section)
    return SectionResponse.model_validate(section)


@router.delete("/learn/library/sections/{section_id}", status_code=204)
async def delete_section(
    section_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_content_role(db, principal, "publisher")
    section = await db.get(LibrarySection, section_id)
    if section is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Раздел не найден")
    in_use = (
        await db.execute(
            select(LibraryMaterial.id)
            .where(LibraryMaterial.section_id == section_id)
            .limit(1)
        )
    ).scalar_one_or_none() is not None
    has_children = (
        await db.execute(
            select(LibrarySection.id).where(LibrarySection.parent_id == section_id).limit(1)
        )
    ).scalar_one_or_none() is not None
    if in_use or has_children:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Раздел не пуст — перенесите материалы и подразделы",
        )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type="library_section",
        object_id=section.id,
        object_label=section.title,
    )
    await db.delete(section)
    await db.commit()


# --- Материалы ---------------------------------------------------------------


@router.post("/learn/library/materials", response_model=MaterialResponse, status_code=201)
async def create_material(
    body: MaterialCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MaterialResponse:
    await require_content_role(db, principal, "author")
    if body.kind == "link" and not body.url:
        raise HTTPException(status_code=422, detail="Для ссылки укажите URL")
    material = LibraryMaterial(
        tenant_id=principal.tenant_id,
        title=body.title,
        description=body.description,
        kind=body.kind,
        url=body.url if body.kind == "link" else None,
        section_id=body.section_id,
        requires_acknowledgement=body.requires_acknowledgement,
        re_ack_on_new_version=body.re_ack_on_new_version,
        ack_deadline_days=body.ack_deadline_days,
        review_period_months=body.review_period_months,
        owner_id=body.owner_id or principal.employee_id,
        created_by=principal.employee_id,
    )
    db.add(material)
    await db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type=_OBJECT_TYPE,
        object_id=material.id,
        object_label=material.title,
    )
    await db.commit()
    await db.refresh(material)
    return MaterialResponse.model_validate(material)


@router.patch("/learn/library/materials/{material_id}", response_model=MaterialResponse)
async def update_material(
    material_id: UUID,
    body: MaterialUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MaterialResponse:
    role = await require_content_role(db, principal, "author")
    material = await _get_material_or_404(db, material_id)
    _require_manage(material, principal, role)
    fields = body.model_dump(exclude_unset=True)
    diff = audit.field_diff(
        material, {**{k: getattr(material, k) for k in fields}, **fields}, list(fields)
    )
    for name, value in fields.items():
        setattr(material, name, value)
    if diff:
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="update",
            object_type=_OBJECT_TYPE,
            object_id=material.id,
            object_label=material.title,
            diff=diff,
        )
    await _reindex(db, material)
    await db.commit()
    await db.refresh(material)
    return MaterialResponse.model_validate(material)


@router.delete("/learn/library/materials/{material_id}", status_code=204)
async def delete_material(
    material_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await require_content_role(db, principal, "author")
    material = await _get_material_or_404(db, material_id)
    _require_manage(material, principal, role)
    # Hard delete — только для никогда не публиковавшихся (иначе archive).
    if material.published_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Материал публиковался — используйте архив, история сохраняется",
        )
    file_versions = (
        (
            await db.execute(
                select(MaterialVersion).where(MaterialVersion.material_id == material_id)
            )
        )
        .scalars()
        .all()
    )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type=_OBJECT_TYPE,
        object_id=material.id,
        object_label=material.title,
    )
    await delete_document(db, object_type=_OBJECT_TYPE, object_id=material.id)
    await db.delete(material)
    await db.commit()
    for v in file_versions:
        try:
            absolute_path(v.storage_key).unlink(missing_ok=True)
        except ValueError:
            pass


@router.post(
    "/learn/library/materials/{material_id}/versions",
    response_model=MaterialResponse,
    status_code=201,
)
async def upload_version(
    material_id: UUID,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MaterialResponse:
    await enforce_rate_limit(
        bucket="attach:upload",
        employee_id=str(principal.employee_id),
        limit=30,
        window_sec=60,
    )
    role = await require_content_role(db, principal, "author")
    material = await _get_material_or_404(db, material_id)
    _require_manage(material, principal, role)
    if material.kind != "file":
        raise HTTPException(status_code=422, detail="У материала-ссылки нет версий")

    mime = file.content_type or "application/octet-stream"
    if mime not in LIBRARY_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Тип файла {mime!r} не разрешён в библиотеке",
        )
    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла обязательно")

    next_no = (
        (
            await db.execute(
                select(func.max(MaterialVersion.version_no)).where(
                    MaterialVersion.material_id == material_id
                )
            )
        ).scalar_one()
        or 0
    ) + 1
    storage_key, sanitized = storage_key_for_version(
        material.tenant_id, material.id, next_no, file.filename
    )
    dest = absolute_path(storage_key)
    dest.parent.mkdir(parents=True, exist_ok=True)

    max_bytes = get_settings().attachment_max_bytes
    written = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Файл больше лимита {max_bytes // (1024 * 1024)} МБ",
                    )
                fh.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Не удалось сохранить файл") from exc

    version = MaterialVersion(
        tenant_id=material.tenant_id,
        material_id=material.id,
        version_no=next_no,
        storage_key=storage_key,
        file_name=sanitized,
        mime=mime,
        size_bytes=written,
        uploaded_by=principal.employee_id,
    )
    db.add(version)
    material.current_version_no = next_no
    # Обновление документа сбрасывает отсчёт актуализации (ТЗ §8.2).
    if material.review_period_months:
        material.next_review_at = datetime.now(UTC) + timedelta(
            days=30 * material.review_period_months
        )
    # Очередь извлечения текста (воркер — 2-я волна).
    db.add(
        TextExtractionJob(
            tenant_id=material.tenant_id,
            object_type=_OBJECT_TYPE,
            object_id=material.id,
            storage_key=storage_key,
            mime=mime,
        )
    )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type=_OBJECT_TYPE,
        object_id=material.id,
        object_label=material.title,
        diff={"version": {"old": next_no - 1 or None, "new": next_no}},
    )
    await _reindex(db, material)

    notify_ids: list[UUID] = []
    if (
        material.status == "published"
        and material.requires_acknowledgement
        and material.re_ack_on_new_version
        and next_no > 1
    ):
        # Новая версия обнуляет ознакомления — уведомить аудиторию заново.
        members = await _audience_profile_ids(db, material.audience_id)
        notify_ids = await _not_acked(db, material, members)

    await db.commit()
    if notify_ids:
        await notify_ack_required(db, material, notify_ids)
        await db.commit()
    await db.refresh(material)
    resp = MaterialResponse.model_validate(material)
    resp.current_version = VersionResponse.model_validate(version)
    return resp


@router.get("/learn/library/materials/{material_id}/versions")
async def list_versions(
    material_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[VersionResponse]:
    role = await resolve_content_role(db, principal)
    material = await _get_material_or_404(db, material_id)
    profile = await get_profile(db, principal)
    if not await _material_visible_to(
        db, material, principal, role, profile.id if profile else None
    ):
        raise HTTPException(status_code=404, detail="Материал не найден")
    rows = (
        (
            await db.execute(
                select(MaterialVersion)
                .where(MaterialVersion.material_id == material_id)
                .order_by(MaterialVersion.version_no.desc())
            )
        )
        .scalars()
        .all()
    )
    return [VersionResponse.model_validate(v) for v in rows]


# --- Lifecycle / audience ----------------------------------------------------


@router.post("/learn/library/materials/{material_id}/status", response_model=MaterialResponse)
async def change_status(
    material_id: UUID,
    body: StatusBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MaterialResponse:
    role = await require_content_role(db, principal, "author")
    material = await _get_material_or_404(db, material_id)
    _require_manage(material, principal, role)
    if body.status == "published" and material.kind == "file" and not material.current_version_no:
        raise HTTPException(status_code=422, detail="Сначала загрузите файл")

    was_published = material.status == "published"
    lifecycle.transition(
        db,
        material,
        body.status,
        actor_id=principal.employee_id,
        role=role,
        tenant_id=principal.tenant_id,
        object_type=_OBJECT_TYPE,
        object_label=material.title,
    )
    await _reindex(db, material)

    notify_ids: list[UUID] = []
    if material.status == "published" and not was_published and material.requires_acknowledgement:
        members = await _audience_profile_ids(db, material.audience_id)
        notify_ids = await _not_acked(db, material, members)

    await db.commit()
    if notify_ids:
        await notify_ack_required(db, material, notify_ids)
        await db.commit()
    await db.refresh(material)
    return MaterialResponse.model_validate(material)


@router.put("/learn/library/materials/{material_id}/audience", response_model=MaterialResponse)
async def set_material_audience(
    material_id: UUID,
    body: AudienceBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MaterialResponse:
    await require_content_role(db, principal, "publisher")
    material = await _get_material_or_404(db, material_id)
    try:
        audience_id, diff = await set_object_audience(
            db,
            tenant_id=principal.tenant_id,
            current_audience_id=material.audience_id,
            is_all=body.is_all,
            rules=_rule_specs(body),
            object_hint=f"{_OBJECT_TYPE}:{material.id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    material.audience_id = audience_id
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="access_change",
        object_type=_OBJECT_TYPE,
        object_id=material.id,
        object_label=material.title,
    )
    await _reindex(db, material)

    notify_ids: list[UUID] = []
    if (
        material.status == "published"
        and material.requires_acknowledgement
        and diff is not None
        and diff.added
    ):
        notify_ids = await _not_acked(db, material, diff.added)

    await db.commit()
    if notify_ids:
        await notify_ack_required(db, material, notify_ids)
        await db.commit()
    await db.refresh(material)
    return MaterialResponse.model_validate(material)


# --- Чтение / ознакомление ---------------------------------------------------


@router.post("/learn/library/materials/{material_id}/open", status_code=204)
async def track_open(
    material_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Фиксация открытия (для link-материалов фронт зовёт при клике)."""
    role = await resolve_content_role(db, principal)
    material = await _get_material_or_404(db, material_id)
    profile = await get_profile(db, principal)
    if profile is None or not await _material_visible_to(
        db, material, principal, role, profile.id
    ):
        raise HTTPException(status_code=404, detail="Материал не найден")
    await _track_open(
        db, tenant_id=material.tenant_id, profile_id=profile.id, material_id=material.id
    )
    await db.commit()


@router.get("/learn/library/materials/{material_id}/download")
async def download_material(
    material_id: UUID,
    version: int | None = Query(default=None),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    role = await resolve_content_role(db, principal)
    material = await _get_material_or_404(db, material_id)
    profile = await get_profile(db, principal)
    if not await _material_visible_to(
        db, material, principal, role, profile.id if profile else None
    ):
        raise HTTPException(status_code=404, detail="Материал не найден")
    version_no = version or material.current_version_no
    if version_no is None:
        raise HTTPException(status_code=404, detail="У материала нет файла")
    row = (
        await db.execute(
            select(MaterialVersion).where(
                MaterialVersion.material_id == material_id,
                MaterialVersion.version_no == version_no,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    path = absolute_path(row.storage_key)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Файл отсутствует в хранилище")
    if profile is not None:
        await _track_open(
            db, tenant_id=material.tenant_id, profile_id=profile.id, material_id=material.id
        )
        await db.commit()
    return FileResponse(path, media_type=row.mime, filename=row.file_name)


@router.post("/learn/library/materials/{material_id}/ack", response_model=MaterialResponse)
async def acknowledge(
    material_id: UUID,
    body: AckBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> MaterialResponse:
    await enforce_rate_limit(
        bucket="doc:ack",
        employee_id=str(principal.employee_id),
        limit=60,
        window_sec=60,
    )
    role = await resolve_content_role(db, principal)
    material = await _get_material_or_404(db, material_id)
    profile = await get_profile(db, principal)
    if profile is None or not await _material_visible_to(
        db, material, principal, role, profile.id
    ):
        raise HTTPException(status_code=404, detail="Материал не найден")
    if not material.requires_acknowledgement or material.status != "published":
        raise HTTPException(status_code=422, detail="Материал не требует ознакомления")

    effective = _effective_ack_version(material)
    if body.version_no != effective:
        # Пока читал — вышла новая версия: фронт перечитывает материал.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Версия документа обновилась — откройте актуальную",
        )
    opened = (
        await db.execute(
            select(ViewHistory.profile_id).where(
                ViewHistory.profile_id == profile.id,
                ViewHistory.object_type == _OBJECT_TYPE,
                ViewHistory.object_id == material.id,
            )
        )
    ).scalar_one_or_none() is not None
    if not opened:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Сначала откройте документ",
        )

    stmt = pg_insert(MaterialAcknowledgement).values(
        material_id=material.id,
        version_no=effective,
        profile_id=profile.id,
        tenant_id=material.tenant_id,
    )
    await db.execute(
        stmt.on_conflict_do_nothing(
            index_elements=["material_id", "version_no", "profile_id"]
        )
    )
    await db.commit()
    await db.refresh(material)
    resp = MaterialResponse.model_validate(material)
    resp.opened_by_me = True
    resp.acked_by_me = True
    resp.ack_pending = False
    return resp


# --- Отчёт об ознакомлении ---------------------------------------------------


@router.get(
    "/learn/library/materials/{material_id}/ack-report", response_model=AckReportResponse
)
async def ack_report(
    material_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> AckReportResponse:
    role = await resolve_content_role(db, principal)
    material = await _get_material_or_404(db, material_id)
    scope = await resolve_scope(db, principal)
    if not lifecycle.can(role, "publisher") and scope.kind != "stores":
        raise HTTPException(status_code=403, detail="Нет доступа к отчёту")

    # Знаменатель: АКТИВНЫЕ члены аудитории (+granted_at); acks уволенных
    # остаются в истории, но в знаменатель не входят.
    if material.audience_id is not None:
        member_rows = await db.execute(
            select(EmployeeProfile, AudienceMember.granted_at)
            .join(AudienceMember, AudienceMember.profile_id == EmployeeProfile.id)
            .where(
                AudienceMember.audience_id == material.audience_id,
                EmployeeProfile.status == "active",
            )
        )
        members: list[tuple[EmployeeProfile, datetime | None]] = [
            (r[0], r[1]) for r in member_rows
        ]
    else:
        members = [
            (p, None)
            for p in (
                await db.execute(
                    select(EmployeeProfile).where(EmployeeProfile.status == "active")
                )
            )
            .scalars()
            .all()
        ]

    if scope.kind == "stores" and not lifecycle.can(role, "publisher"):
        members = [
            (p, g)
            for p, g in members
            if p.store_id in scope.store_ids or p.id == scope.profile_id
        ]

    profile_ids = [p.id for p, _ in members]
    effective = _effective_ack_version(material)
    ack_stmt = select(
        MaterialAcknowledgement.profile_id, MaterialAcknowledgement.acknowledged_at
    ).where(
        MaterialAcknowledgement.material_id == material.id,
        MaterialAcknowledgement.profile_id.in_(profile_ids or [UUID(int=0)]),
    )
    if material.re_ack_on_new_version:
        ack_stmt = ack_stmt.where(MaterialAcknowledgement.version_no == effective)
    acked_at = {r[0]: r[1] for r in await db.execute(ack_stmt)}

    opened_at: dict[UUID, datetime] = {}
    if profile_ids:
        opened_at = {
            r[0]: r[1]
            for r in await db.execute(
                select(ViewHistory.profile_id, ViewHistory.first_viewed_at).where(
                    ViewHistory.object_type == _OBJECT_TYPE,
                    ViewHistory.object_id == material.id,
                    ViewHistory.profile_id.in_(profile_ids),
                )
            )
        }

    now = datetime.now(UTC)
    rows = []
    for p, granted_at in sorted(members, key=lambda x: x[0].full_name):
        deadline = None
        if material.ack_deadline_days and material.published_at:
            base = material.published_at
            if granted_at is not None and granted_at > base:
                base = granted_at
            deadline = base + timedelta(days=material.ack_deadline_days)
        ack_ts = acked_at.get(p.id)
        rows.append(
            AckReportRow(
                profile_id=p.id,
                full_name=p.full_name,
                store_id=p.store_id,
                granted_at=granted_at,
                opened_at=opened_at.get(p.id),
                acknowledged_at=ack_ts,
                deadline_at=deadline,
                overdue=bool(deadline and ack_ts is None and now > deadline),
            )
        )
    return AckReportResponse(
        material_id=material.id,
        total=len(rows),
        acked=sum(1 for r in rows if r.acknowledged_at is not None),
        rows=rows,
    )
