"""Шаблоны проектов (0060): библиотека, шаблон с нуля, шаблон из проекта,
проект по шаблону.

Шаблоны прячет политика RLS («замок», см. миграцию 0060 и `app/db.py`).
Здесь область открывается ЯВНО: `'all'` — только в библиотеке, `'<id>'` —
для одного шаблона. Страницу шаблона (доска, карточки, участники) обслуживают
обычные ручки проекта через `deps.get_db_template_page`.

Префикс `/templates`, а не `/projects/templates`: второй совпал бы с
`GET /projects/{project_id}` и отвечал бы 422 на разборе UUID.

Доступ: видят и используют — те, кто может создавать проекты; правят —
автор и hub-admin; сохранить проект как шаблон — его владелец (содержимое
уходит в общую библиотеку). Выключенный модуль — 404 (кроме `settings`).
"""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import _project_to_response
from app.config import get_settings
from app.db import TEMPLATE_SCOPE_ALL, set_template_scope
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.attachment import TaskAttachment
from app.models.project import Project, ProjectMember
from app.models.project_folder import ProjectFolder
from app.models.shadow import ShadowUser
from app.models.task import Task
from app.schemas.project import ProjectResponse
from app.schemas.project_template import (
    CopyPreview,
    CopyReportResponse,
    ProjectFromTemplate,
    ProjectFromTemplateResponse,
    SaveAsTemplate,
    TemplateCreate,
    TemplateListItem,
    TemplateSettings,
    TemplateSettingsUpdate,
    TemplateUpdate,
)
from app.services import audit
from app.services.attachments import purge_blobs
from app.services.learn_media import check_free_space
from app.services.notify import notify_assigned_from_template
from app.services.personal_projects import assert_not_personal
from app.services.project_access import (
    MANAGE_ROLES,
    can_edit_template,
    can_view_templates,
    open_template_scope,
    require_project_role,
)
from app.services.project_badge import badge_url
from app.services.project_key import generate_unique_key
from app.services.project_templates import gate
from app.services.project_templates.copy import (
    TEMPLATE_MAX_TASKS,
    CopyPlan,
    apply_copy,
    plan_copy,
    preview_payload,
)
from app.services.projects import create_project_record
from app.services.taskdates import display_today

router = APIRouter(tags=["project-templates"])
log = structlog.get_logger("project_templates")

_ADMIN = require_auth(roles=["admin"])
_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Шаблон не найден")
_VIEW_DENIED = "Шаблоны доступны тем, кто может создавать проекты"


async def _require_module(db: AsyncSession, principal: Principal) -> None:
    if not await gate.templates_enabled_for(db, principal.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    if not await can_view_templates(db, principal):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_VIEW_DENIED)


async def _open_template(
    db: AsyncSession, principal: Principal, template_id: UUID, *, mode: str
) -> Project:
    """Открыть область одного шаблона и вернуть его; иначе 404."""
    opened = await open_template_scope(db, principal, project_id=template_id, mode=mode)
    if opened is None:
        raise _NOT_FOUND
    project = await db.get(Project, template_id)
    if project is None or not project.is_template:
        raise _NOT_FOUND
    return project


def _assert_disk(plan: CopyPlan) -> None:
    """Гейт места — как у загрузки вложения. Запас на полный объём оставляем
    даже при жёстких ссылках: ночной снимок файлов лежит на том же диске."""
    if not plan.attachments:
        return
    need = get_settings().media_min_free_bytes + plan.attachment_bytes
    if check_free_space() < need:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="На сервере мало места для копий вложений. Снимите галочку "
            "«Вложения» или сообщите администратору.",
        )


def _disk_ok(plan: CopyPlan) -> bool:
    if not plan.attachments:
        return True
    return check_free_space() >= get_settings().media_min_free_bytes + plan.attachment_bytes


def _assert_not_too_big(plan: CopyPlan) -> None:
    if plan.too_big:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"В проекте {plan.task_count} задач — больше предела "
            f"{TEMPLATE_MAX_TASKS} для копирования",
        )


async def _purge(keys: list[str]) -> None:
    if keys:
        await asyncio.to_thread(purge_blobs, keys)


# ─── Настройки модуля (живут всегда при включённом env) ─────────────────────
# Объявлены ДО `/templates/{template_id}`: иначе «settings» попадал бы в
# разбор UUID и отвечал 422.


@router.get("/templates/settings", response_model=TemplateSettings)
async def get_template_settings(
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> TemplateSettings:
    if not gate.env_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    return TemplateSettings(
        enabled=await gate.tenant_enabled(db, principal.tenant_id), env_enabled=True
    )


@router.put("/templates/settings", response_model=TemplateSettings)
async def put_template_settings(
    body: TemplateSettingsUpdate,
    principal: Principal = Depends(_ADMIN),
    db: AsyncSession = Depends(get_db),
) -> TemplateSettings:
    if not gate.env_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    old = await gate.tenant_enabled(db, principal.tenant_id)
    if old != body.enabled:
        await gate.set_tenant_enabled(db, principal.tenant_id, body.enabled)
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="update",
            object_type="project_template_settings",
            object_label="Шаблоны проектов",
            diff={"enabled": {"old": old, "new": body.enabled}},
        )
        await db.commit()
    return TemplateSettings(enabled=body.enabled, env_enabled=True)


# ─── Библиотека ──────────────────────────────────────────────────────────────


@router.get("/templates", response_model=list[TemplateListItem])
async def list_templates(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateListItem]:
    await _require_module(db, principal)
    # Единственное место, где открыта область 'all': список, без правок.
    await set_template_scope(db, TEMPLATE_SCOPE_ALL)
    templates = list(
        (
            await db.execute(
                select(Project).where(Project.is_template.is_(True)).order_by(Project.name)
            )
        ).scalars()
    )
    if not templates:
        return []
    ids = [t.id for t in templates]
    # Задачи верхнего уровня — как «N задач» в шапке проекта (`_task_counts`):
    # на проде библиотека писала «382 задачи», а страница шаблона — «298 задач».
    task_counts = dict(
        (
            await db.execute(
                select(Task.project_id, func.count())
                .where(
                    Task.project_id.in_(ids),
                    Task.archived_at.is_(None),
                    Task.parent_task_id.is_(None),
                )
                .group_by(Task.project_id)
            )
        ).all()
    )
    att = {
        pid: (n, int(size or 0))
        for pid, n, size in (
            await db.execute(
                select(
                    Task.project_id,
                    func.count(TaskAttachment.id),
                    func.sum(TaskAttachment.size_bytes),
                )
                .join(Task, Task.id == TaskAttachment.task_id)
                .where(Task.project_id.in_(ids), Task.archived_at.is_(None))
                .group_by(Task.project_id)
            )
        ).all()
    }
    member_counts = dict(
        (
            await db.execute(
                select(ProjectMember.project_id, func.count())
                .join(ShadowUser, ShadowUser.employee_id == ProjectMember.employee_id)
                .where(ProjectMember.project_id.in_(ids), ShadowUser.deleted_at.is_(None))
                .group_by(ProjectMember.project_id)
            )
        ).all()
    )
    use_counts = dict(
        (
            await db.execute(
                select(Project.created_from_template_id, func.count())
                .where(Project.created_from_template_id.in_(ids))
                .group_by(Project.created_from_template_id)
            )
        ).all()
    )
    authors = {
        e: (name or email, deleted is not None)
        for e, name, email, deleted in (
            await db.execute(
                select(
                    ShadowUser.employee_id,
                    ShadowUser.full_name,
                    ShadowUser.email,
                    ShadowUser.deleted_at,
                ).where(ShadowUser.employee_id.in_({t.created_by for t in templates}))
            )
        ).all()
    }
    out: list[TemplateListItem] = []
    for t in templates:
        author_name, author_deleted = authors.get(t.created_by, (None, False))
        n_att, att_bytes = att.get(t.id, (0, 0))
        out.append(
            TemplateListItem(
                id=t.id,
                key=t.key,
                name=t.name,
                description=t.description,
                badge_emoji=t.badge_emoji,
                badge_url=badge_url(t),
                template_anchor_on=t.template_anchor_on,
                created_by=t.created_by,
                author_name=author_name,
                author_deleted=author_deleted,
                task_count=int(task_counts.get(t.id, 0)),
                attachment_count=int(n_att),
                attachment_bytes=att_bytes,
                member_count=int(member_counts.get(t.id, 0)),
                use_count=int(use_counts.get(t.id, 0)),
                can_edit=can_edit_template(principal, t.created_by),
                updated_at=t.updated_at,
            )
        )
    return out


@router.post("/templates", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    await enforce_rate_limit(
        bucket="template:write", employee_id=str(principal.employee_id), limit=30, window_sec=60
    )
    await _require_module(db, principal)
    # Ключ — до открытия области: подбор смотрит только живые проекты.
    key = await generate_unique_key(db, name=body.name, tenant_id=principal.tenant_id)
    template_id = uuid4()
    await set_template_scope(db, str(template_id))
    project = await create_project_record(
        db,
        tenant_id=principal.tenant_id,
        created_by=principal.employee_id,
        name=body.name.strip(),
        key=key,
        description=body.description,
        project_id=template_id,
        is_template=True,
        template_anchor_on=body.anchor_on or display_today(),
    )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type="project_template",
        object_id=template_id,
        object_label=project.name,
    )
    await db.commit()
    await db.refresh(project)
    return _project_to_response(project, None, principal=principal, counts=(0, 0))


@router.patch("/templates/{template_id}", response_model=ProjectResponse)
async def update_template(
    template_id: UUID,
    body: TemplateUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    await enforce_rate_limit(
        bucket="template:write", employee_id=str(principal.employee_id), limit=30, window_sec=60
    )
    await _require_module(db, principal)
    project = await _open_template(db, principal, template_id, mode="edit")
    # Даты задач не двигаются — меняется только сдвиг при создании проекта.
    project.template_anchor_on = body.anchor_on
    await db.commit()
    await db.refresh(project)
    return _project_to_response(project, None, principal=principal)


# ─── Сохранить проект как шаблон ─────────────────────────────────────────────


async def _load_source(db: AsyncSession, principal: Principal, project_id: UUID) -> Project:
    """Источник — живой проект, где человек владелец и может создавать проекты.

    Личный — 409 даже hub-admin'у: он проходит `require_project_role` в любой
    проект, а `plan_copy` читает задачи без `personal_task_scope` — личные
    заметки вместе с поручениями коллег ушли бы в общую библиотеку.
    """
    project, _role = await require_project_role(db, project_id, principal, allow=MANAGE_ROLES)
    assert_not_personal(project, action="сохранить как шаблон")
    if project.is_template:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Это уже шаблон — создайте по нему проект",
        )
    return project


@router.get("/projects/{project_id}/template-preview", response_model=CopyPreview)
async def preview_save_as_template(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CopyPreview:
    await _require_module(db, principal)
    source = await _load_source(db, principal, project_id)
    plan = await plan_copy(db, source)
    data = preview_payload(plan, shift=0, today=display_today(), actor_id=principal.employee_id)
    # В шаблон не копируется сохраняющий, и сводки нет вовсе.
    data["members"] = sum(
        1 for e, _r, alive in plan.members if alive and e != principal.employee_id
    )
    data["notify_people"] = 0
    return CopyPreview(**data, disk_ok=_disk_ok(plan))


@router.post(
    "/projects/{project_id}/save-as-template",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_as_template(
    project_id: UUID,
    body: SaveAsTemplate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    await enforce_rate_limit(
        bucket="template:copy", employee_id=str(principal.employee_id), limit=5, window_sec=60
    )
    await _require_module(db, principal)
    source = await _load_source(db, principal, project_id)
    plan = await plan_copy(
        db,
        source,
        include_members=body.include_members,
        include_attachments=body.include_attachments,
    )
    _assert_not_too_big(plan)
    _assert_disk(plan)
    key = await generate_unique_key(db, name=body.name, tenant_id=principal.tenant_id)
    anchor = body.anchor_on or preview_payload(
        plan, shift=0, today=display_today(), actor_id=principal.employee_id
    )["suggested_anchor_on"]
    template_id = uuid4()
    created_keys: list[str] = []
    try:
        await set_template_scope(db, str(template_id))
        template = await create_project_record(
            db,
            tenant_id=principal.tenant_id,
            created_by=principal.employee_id,
            name=body.name.strip(),
            key=key,
            description=source.description,
            project_id=template_id,
            is_template=True,
            template_anchor_on=anchor,
        )
        report = await apply_copy(
            db,
            plan,
            template,
            actor_id=principal.employee_id,
            shift=0,
            created_keys=created_keys,
        )
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="create",
            object_type="project_template",
            object_id=template_id,
            object_label=template.name,
            diff={"from_project": str(source.id), "tasks": report.tasks + report.subtasks},
        )
        await db.commit()
    except BaseException:
        await db.rollback()
        await _purge(created_keys)
        raise
    await db.refresh(template)
    return _project_to_response(
        template, None, principal=principal, counts=(report.tasks + report.subtasks, 0)
    )


# ─── Проект по шаблону ───────────────────────────────────────────────────────


def _shift_for(template: Project, start_on: date | None) -> tuple[date, int]:
    start = start_on or display_today()
    anchor = template.template_anchor_on or start
    return start, (start - anchor).days


@router.get("/templates/{template_id}/preview", response_model=CopyPreview)
async def preview_project_from_template(
    template_id: UUID,
    start_on: date | None = Query(default=None),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CopyPreview:
    await _require_module(db, principal)
    template = await _open_template(db, principal, template_id, mode="view")
    plan = await plan_copy(db, template)
    start, shift = _shift_for(template, start_on)
    data = preview_payload(plan, shift=shift, today=display_today(), actor_id=principal.employee_id)
    return CopyPreview(**data, shift_days=shift, start_on=start, disk_ok=_disk_ok(plan))


@router.post(
    "/templates/{template_id}/projects",
    response_model=ProjectFromTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_from_template(
    template_id: UUID,
    body: ProjectFromTemplate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectFromTemplateResponse:
    await enforce_rate_limit(
        bucket="template:copy", employee_id=str(principal.employee_id), limit=5, window_sec=60
    )
    await _require_module(db, principal)
    # Старт в прошлом РАЗРЕШЁН (решение владельца 21.09: проект, начатый на
    # прошлой неделе, заводят задним числом). Цена известна и названа человеку
    # до нажатия: задачи со сроком раньше сегодняшнего сразу просрочены, и
    # джоба `overdue` шлёт по каждой напоминание КАЖДЫЙ день в 09:00 —
    # предпросмотр считает их (`overdue_after_shift`), диалог предупреждает.
    template = await _open_template(db, principal, template_id, mode="view")
    if body.folder_id is not None and await db.get(ProjectFolder, body.folder_id) is None:
        # FK тенант не сверяет — `db.get` под RLS обязателен.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Папка не найдена")
    plan = await plan_copy(
        db,
        template,
        include_members=body.include_members,
        include_attachments=body.include_attachments,
    )
    _assert_not_too_big(plan)
    _assert_disk(plan)
    _start, shift = _shift_for(template, body.start_on)
    key = body.key or await generate_unique_key(
        db, name=body.name, tenant_id=principal.tenant_id
    )
    created_keys: list[str] = []
    try:
        project = await create_project_record(
            db,
            tenant_id=principal.tenant_id,
            created_by=principal.employee_id,
            name=body.name.strip(),
            key=key,
            description=template.description,
        )
        project.folder_id = body.folder_id
        project.created_from_template_id = template.id
        project.created_from_template_name = template.name
        report = await apply_copy(
            db,
            plan,
            project,
            actor_id=principal.employee_id,
            shift=shift,
            created_keys=created_keys,
            template_ref=(template.id, template.name),
        )
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="create",
            object_type="project",
            object_id=project.id,
            object_label=project.name,
            diff={
                "from_template": str(template.id),
                "tasks": report.tasks + report.subtasks,
                "shift_days": shift,
            },
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        await _purge(created_keys)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Проект с ключом {key!r} уже существует",
        ) from exc
    except BaseException:
        await db.rollback()
        await _purge(created_keys)
        raise

    # Сводка — ОТДЕЛЬНОЙ транзакцией после commit копии: `dispatch` планирует
    # пуш сразу, и откат копии после него разослал бы пуши о проекте, которого
    # нет. Сбой уведомлений проект не отменяет.
    notified = 0
    try:
        for recipient, count in report.summary.items():
            await notify_assigned_from_template(
                db,
                tenant_id=principal.tenant_id,
                project_id=project.id,
                project_name=project.name,
                template_id=template.id,
                recipient_id=recipient,
                task_count=count,
            )
            notified += 1
        await db.commit()
    except Exception:  # noqa: BLE001 — уведомления не отменяют созданный проект
        await db.rollback()
        log.warning("template.summary_failed", project_id=str(project.id))

    await db.refresh(project)
    response = _project_to_response(
        project, "owner", principal=principal, counts=(report.tasks + report.subtasks, 0)
    )
    return ProjectFromTemplateResponse(
        project=response,
        report=CopyReportResponse(
            tasks=report.tasks,
            subtasks=report.subtasks,
            dropped={
                "archived": report.dropped.archived,
                "orphan_subtasks": report.dropped.orphan_subtasks,
                "recurrence_steps": report.dropped.recurrence_steps,
            },
            dropped_people=report.dropped_people,
            attachments_copied=report.attachments_copied,
            attachments_missing=report.attachments_missing,
            notified=notified,
        ),
    )
