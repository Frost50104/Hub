"""Anonymous public-share-token reader (3.6.12).

`GET /api/public/{token}` is the only endpoint in the app served WITHOUT
`require_auth`. Security model:

1. UUID v4 token (122-bit entropy) is the entire capability.
2. Token lookup happens cross-tenant on `public_share_tokens` (no RLS there).
3. ONLY after a valid + active token is found we `bypass_rls=True` to read
   the entity, scoped to the token's tenant_id.
4. Response goes through a sanitizer: no email, no employee_id, no tenant
   info, no attachment download URLs. Names → initials.
5. Returns 404 for both "token not found" and "token revoked/expired" so a
   probe can't tell which one happened (negligible info-leak, but uniform
   responses are simpler to reason about).

Feature-flag (`SIGNARIS_HUB_PUBLIC_LINKS_ENABLED=false`) returns 503 for the
entire surface — kill switch without redeploy.
"""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session
from app.models.attachment import TaskAttachment
from app.models.project import Project
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskComment
from app.schemas.race import TvTrackResponse
from app.schemas.share import (
    PublicAttachmentMeta,
    PublicComment,
    PublicProjectComment,
    PublicProjectView,
    PublicSection,
    PublicTaskHit,
    PublicTaskView,
)
from app.services.mention_parser import normalize_token
from app.services.people_search import is_token_safe, name_to_token
from app.services.public_token import initials, load_active_token, mask_mentions
from app.services.race import read as race_read
from app.services.race.engine import today_local
from app.services.race.gate import race_enabled_for
from app.services.task_assignees import load_assignee_ids

router = APIRouter(tags=["public"])

_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Ссылка недействительна"
)


@router.get("/public/{token}")
async def get_public(token: UUID) -> PublicTaskView | PublicProjectView:
    settings = get_settings()
    if not settings.public_links_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Публичные ссылки временно отключены",
        )

    # Stage 1 — cross-tenant token lookup (no RLS on public_share_tokens).
    async with tenant_scoped_session(None, bypass_rls=True) as session:
        record = await load_active_token(session, token)
        if record is None:
            raise _NOT_FOUND
        tenant_id = record.tenant_id
        scope = record.scope
        entity_id = record.entity_id

    # Stage 2 — read the entity scoped to the token's tenant. Tenant-скоуп
    # (НЕ bypass): все чтения builders — внутри tenant'а токена, а bypass
    # раскрывал _mention_names словарь имён/email ЧУЖИХ tenant'ов.
    async with tenant_scoped_session(tenant_id) as session:
        if scope == "task":
            return await _build_task_view(session, entity_id)
        if scope == "project":
            return await _build_project_view(session, entity_id)
        raise _NOT_FOUND


@router.get("/public/race/{token}", response_model=TvTrackResponse)
async def get_public_race(token: str, response: Response) -> TvTrackResponse:
    """ТВ-панель «Гусиной гонки» без логина (scope `race`, entity_id = tenant).

    `token: str` с ручным разбором: типизация `UUID` отдавала бы на мусор 422
    с телом pydantic вместо ровного 404. Выключенный модуль — тот же 404:
    «как будто её и не было». Полезная нагрузка — только имена/коды точек
    и числа, ПДн нет по построению (тест `test_race_public`).
    """
    settings = get_settings()
    if not settings.public_links_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Публичные ссылки временно отключены",
        )
    try:
        token_uuid = UUID(token)
    except ValueError:
        raise _NOT_FOUND from None
    async with tenant_scoped_session(None, bypass_rls=True) as session:
        record = await load_active_token(session, token_uuid)
        if record is None or record.scope != "race":
            raise _NOT_FOUND
        tenant_id = record.tenant_id
    async with tenant_scoped_session(tenant_id) as session:
        if not await race_enabled_for(session, tenant_id):
            raise _NOT_FOUND
        contest = await race_read.current_contest(session, tenant_id)
        payload = await race_read.build_track(
            session, contest, today=today_local(), my_store_id=None, tenant_id=tenant_id
        )
    payload.pop("my_store_id", None)
    response.headers["Cache-Control"] = "no-store"
    return TvTrackResponse(**payload)


# ─── Builders ──────────────────────────────────────────────────────────────


async def _initials_for(session: AsyncSession, employee_id: UUID | None) -> str | None:
    if employee_id is None:
        return None
    row = await session.execute(
        select(ShadowUser.full_name, ShadowUser.email).where(
            ShadowUser.employee_id == employee_id
        )
    )
    rec = row.first()
    if rec is None:
        return None
    return initials(rec.full_name, rec.email)


async def _initials_for_many(
    session: AsyncSession, employee_ids: set[UUID]
) -> dict[UUID, str]:
    """{employee_id: инициалы} одним запросом — анти-N+1 на больших досках."""
    if not employee_ids:
        return {}
    rows = await session.execute(
        select(ShadowUser.employee_id, ShadowUser.full_name, ShadowUser.email).where(
            ShadowUser.employee_id.in_(employee_ids)
        )
    )
    return {r.employee_id: initials(r.full_name, r.email) or "" for r in rows.all()}


async def _mention_names(session: AsyncSession) -> dict[str, str]:
    """токен упоминания → display name для mask_mentions.

    Токенов два вида — логин почты и `Имя_Фамилия` (см. mention_parser).
    Неоднозначное имя (полные тёзки) из словаря выбрасывается: показать одно
    ФИО вместо другого здесь безобидно, но правило «неоднозначное не
    резолвится» должно быть одним на весь продукт.

    Tenant-scoped сессия + RLS ограничивают выборку своим tenant'ом.
    """
    rows = await session.execute(
        select(ShadowUser.email, ShadowUser.full_name).limit(500)
    )
    people = [r for r in rows.all() if r.email and r.full_name]
    name_tokens = Counter(
        normalize_token(name_to_token(r.full_name))
        for r in people
        if is_token_safe(r.full_name)
    )
    out: dict[str, str] = {}
    for r in people:
        out[normalize_token(r.email.split("@", 1)[0])] = r.full_name
        if is_token_safe(r.full_name):
            token = normalize_token(name_to_token(r.full_name))
            if name_tokens[token] == 1:
                out[token] = r.full_name
    return out


async def _build_task_view(session: AsyncSession, task_id: UUID) -> PublicTaskView:
    task = await session.get(Task, task_id)
    if task is None or task.archived_at is not None:
        raise _NOT_FOUND

    assignee_ids = (await load_assignee_ids(session, [task.id])).get(task.id, [])
    assignee_inits_by_id = await _initials_for_many(session, set(assignee_ids))
    assignee_inits = [
        assignee_inits_by_id[e] for e in assignee_ids if assignee_inits_by_id.get(e)
    ]
    assignee_init = assignee_inits[0] if assignee_inits else None
    creator_init = await _initials_for(session, task.created_by)

    comment_rows = await session.execute(
        select(
            TaskComment.body,
            TaskComment.created_at,
            ShadowUser.full_name,
            ShadowUser.email,
        )
        .join(
            ShadowUser,
            (ShadowUser.employee_id == TaskComment.author_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(
            TaskComment.task_id == task_id,
            TaskComment.deleted_at.is_(None),
        )
        .order_by(TaskComment.created_at)
    )
    mention_names = await _mention_names(session)
    comments = [
        PublicComment(
            author_initials=initials(r.full_name, r.email),
            body=mask_mentions(r.body, mention_names),
            created_at=r.created_at,
        )
        for r in comment_rows.all()
    ]

    attachment_rows = await session.execute(
        select(
            TaskAttachment.filename,
            TaskAttachment.size_bytes,
            TaskAttachment.mime,
        ).where(TaskAttachment.task_id == task_id)
    )
    attachments = [
        PublicAttachmentMeta(filename=r.filename, size_bytes=r.size_bytes, mime=r.mime)
        for r in attachment_rows.all()
    ]

    return PublicTaskView(
        title=task.title,
        description=task.description,
        done=task.done,
        priority=task.priority,
        start_at=task.start_at,
        due_at=task.due_at,
        start_has_time=task.start_has_time,
        due_has_time=task.due_has_time,
        assignee_initials=assignee_init,
        assignees_initials=assignee_inits,
        created_by_initials=creator_init,
        created_at=task.created_at,
        comments=comments,
        attachments=attachments,
    )


async def _build_project_view(
    session: AsyncSession, project_id: UUID
) -> PublicProjectView:
    project = await session.get(Project, project_id)
    if project is None or project.archived_at is not None:
        raise _NOT_FOUND

    task_rows = await session.execute(
        select(
            Task.id,
            Task.title,
            Task.done,
            Task.priority,
            Task.due_at,
            Task.parent_task_id,
            Task.due_has_time,
        )
        .where(Task.project_id == project_id, Task.archived_at.is_(None))
        .order_by(Task.position)
    )
    rows_all = list(task_rows.all())
    all_task_ids: list[UUID] = [row.id for row in rows_all]

    # Pre-fetch attachment counts in one query — avoids N+1 on large boards.
    has_att_rows = await session.execute(
        select(TaskAttachment.task_id).distinct()
    )
    has_attachments_set = {row[0] for row in has_att_rows.all()}

    # Исполнители + инициалы — два запроса на всю доску (анти-N+1).
    ids_by_task = await load_assignee_ids(session, all_task_ids)
    initials_by_id = await _initials_for_many(
        session, {e for ids in ids_by_task.values() for e in ids}
    )
    inits_by_task: dict[UUID, list[str]] = {
        task_id: [initials_by_id[e] for e in ids if initials_by_id.get(e)]
        for task_id, ids in ids_by_task.items()
    }

    def _row_to_hit(row) -> PublicTaskHit:  # noqa: ANN001 — local helper
        return PublicTaskHit(
            id=row.id,
            title=row.title,
            done=row.done,
            priority=row.priority,
            due_at=row.due_at,
            due_has_time=row.due_has_time,
            assignee_initials=(
                inits_by_task.get(row.id, [None])[0]
                if inits_by_task.get(row.id)
                else None
            ),
            assignees_initials=inits_by_task.get(row.id, []),
            has_attachments=row.id in has_attachments_set,
            is_subtask=row.parent_task_id is not None,
        )

    # Секций больше нет — отдаём ОДИН синтетический бакет. Ключ `sections` в
    # ответе обязан остаться: старый бандл публичной страницы читает
    # `data.sections.length` без проверки, и его исчезновение дало бы белый
    # экран, а вкладку `/p/` держат открытой днями.
    sections: list[PublicSection] = []
    if rows_all:
        sections.append(
            PublicSection(
                id=project.id,  # synthetic — UI uses project.id as anchor
                # Не имя проекта: страница уже озаглавлена им, и заголовок
                # группы дублировал бы его. Старый бандл рисует `s.name`
                # как есть, поэтому имя решает сервер.
                name="Задачи",
                tasks=[_row_to_hit(r) for r in rows_all],
            )
        )

    # Top-10 most recent comments across every visible task — gives a public
    # viewer a quick "what's the team talking about?" without revealing names.
    recent_comment_rows = await session.execute(
        select(
            TaskComment.body,
            TaskComment.created_at,
            Task.title,
            ShadowUser.full_name,
            ShadowUser.email,
        )
        .join(Task, Task.id == TaskComment.task_id)
        .join(
            ShadowUser,
            (ShadowUser.employee_id == TaskComment.author_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(
            Task.project_id == project_id,
            Task.archived_at.is_(None),
            TaskComment.deleted_at.is_(None),
        )
        .order_by(TaskComment.created_at.desc())
        .limit(10)
    )
    mention_names = await _mention_names(session)
    recent_comments = [
        PublicProjectComment(
            task_title=r.title,
            author_initials=initials(r.full_name, r.email),
            body=mask_mentions(r.body, mention_names),
            created_at=r.created_at,
        )
        for r in recent_comment_rows.all()
    ]

    return PublicProjectView(
        name=project.name,
        description=project.description,
        sections=sections,
        recent_comments=recent_comments,
    )
