"""Projects + project_members API."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from signaris_auth import Principal
from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_scoped_session
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.attachment import TaskAttachment
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.models.project_folder import ProjectFolder
from app.models.shadow import ShadowUser
from app.models.share import PublicShareToken
from app.models.task import Task
from app.schemas.project import (
    ProjectBadgeUpdate,
    ProjectCreate,
    ProjectFavoriteUpdate,
    ProjectFolderAssign,
    ProjectMemberAdd,
    ProjectMemberResponse,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectUpdate,
)
from app.services import audit
from app.services.attachments import (
    SNIFF_HEAD_BYTES,
    absolute_path,
    purge_blobs,
    resolve_mime,
    sniff_mismatch,
)
from app.services.learn_media import check_free_space
from app.services.personal_projects import (
    assert_full_project_access,
    assert_not_personal,
    not_personal,
    personal_task_scope,
)
from app.services.project_access import (
    CREATE_PROJECT_DENIED,
    EDIT_ROLES,
    can_create_project,
    capabilities,
    fetch_project_or_404,
    is_hub_admin,
    require_project_role,
)
from app.services.project_badge import (
    BADGE_MAX_BYTES,
    BADGE_MIME_EXT,
    badge_url,
    storage_key_for_badge,
    verify_badge_signature,
)
from app.services.project_key import generate_unique_key
from app.services.projects import create_project_record

router = APIRouter(tags=["projects"])


async def _task_counts(
    db: AsyncSession, project_ids: Sequence[UUID]
) -> dict[UUID, tuple[int, int]]:
    """{project_id: (всего, закрыто)} одним GROUP BY.

    Считаем только неархивные задачи верхнего уровня: подзадачи живут в
    карточке родителя и в счётчике проекта не участвуют — иначе «26 задач» в
    шапке не сойдётся с числом строк в списке.
    """
    ids = list(dict.fromkeys(project_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(
            Task.project_id,
            func.count(),
            func.count().filter(Task.done),
        )
        .where(
            Task.project_id.in_(ids),
            Task.archived_at.is_(None),
            Task.parent_task_id.is_(None),
        )
        .group_by(Task.project_id)
    )
    return {pid: (total, done) for pid, total, done in rows.all()}


def _project_to_response(
    project: Project,
    my_role: str | None,
    is_favorite: bool = False,
    *,
    principal: Principal,
    counts: tuple[int, int] | None = None,
) -> ProjectResponse:
    """my_role — ФАКТИЧЕСКОЕ членство (для бейджа роли), может быть None у
    hub:admin вне проекта. Права для UI считаются отдельно: у админа они полные
    независимо от членства."""
    can_edit, can_manage = capabilities(principal, my_role)  # type: ignore[arg-type]
    return ProjectResponse(
        id=project.id,
        key=project.key,
        name=project.name,
        description=project.description,
        badge_emoji=project.badge_emoji,
        # Чистая функция от строки и секрета, без обращения к БД — поэтому её
        # можно звать на каждой строке списка проектов без N+1.
        badge_url=badge_url(project),
        archived_at=project.archived_at,
        folder_id=project.folder_id,
        created_by=project.created_by,
        created_at=project.created_at,
        updated_at=project.updated_at,
        my_role=my_role,  # type: ignore[arg-type]
        is_favorite=is_favorite,
        is_personal=project.personal_owner_id is not None,
        can_edit=can_edit,
        can_manage=can_manage,
        task_count=counts[0] if counts else None,
        done_count=counts[1] if counts else None,
    )


async def _my_membership(
    db: AsyncSession, project_id: UUID, employee_id: UUID
) -> tuple[str | None, bool]:
    """(role, is_favorite) текущего пользователя; (None, False) вне членства."""
    row = (
        await db.execute(
            select(ProjectMember.role, ProjectMember.is_favorite).where(
                ProjectMember.project_id == project_id,
                ProjectMember.employee_id == employee_id,
            )
        )
    ).first()
    if row is None:
        return None, False
    return row.role, row.is_favorite


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectResponse]:
    # hub:admin sees every project in the tenant; everyone else only those
    # they're a member of. RLS already restricts to tenant scope.
    #
    # Личные проекты не отдаём НИКОМУ — ни владельцу, ни админу: у каждого
    # сотрудника свой, и в сайдбаре с «Недавними проектами» они были бы шумом.
    # Вход в личное — секция «ЛИЧНОЕ» на /my (services/personal_projects.py).
    if is_hub_admin(principal):
        stmt = select(Project).where(not_personal())
        if not include_archived:
            stmt = stmt.where(Project.archived_at.is_(None))
        rows = (await db.execute(stmt.order_by(Project.created_at.desc()))).scalars().all()
        # Bulk-load my_role + is_favorite so admin still sees their state.
        if rows:
            roles_q = await db.execute(
                select(
                    ProjectMember.project_id,
                    ProjectMember.role,
                    ProjectMember.is_favorite,
                ).where(
                    ProjectMember.employee_id == principal.employee_id,
                    ProjectMember.project_id.in_([p.id for p in rows]),
                )
            )
            member_map = {pid: (role, fav) for pid, role, fav in roles_q.all()}
        else:
            member_map = {}
        counts = await _task_counts(db, [p.id for p in rows])
        return [
            _project_to_response(
                p,
                *member_map.get(p.id, (None, False)),
                principal=principal,
                counts=counts.get(p.id, (0, 0)),
            )
            for p in rows
        ]

    stmt = (
        select(Project, ProjectMember.role, ProjectMember.is_favorite)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.employee_id == principal.employee_id, not_personal())
    )
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    rows = (await db.execute(stmt.order_by(Project.created_at.desc()))).all()
    counts = await _task_counts(db, [p.id for (p, _role, _fav) in rows])
    return [
        _project_to_response(
            p, role, fav, principal=principal, counts=counts.get(p.id, (0, 0))
        )
        for (p, role, fav) in rows
    ]


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    if not await can_create_project(db, principal):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=CREATE_PROJECT_DENIED
        )

    key = body.key
    if key is None:
        try:
            key = await generate_unique_key(
                db, name=body.name, tenant_id=principal.tenant_id
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Не удалось подобрать уникальный ключ — задайте его вручную",
            ) from exc

    project = await create_project_record(
        db,
        tenant_id=principal.tenant_id,
        created_by=principal.employee_id,
        name=body.name,
        key=key,
        description=body.description,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Проект с ключом {key!r} уже существует",
        ) from exc
    await db.refresh(project)
    return _project_to_response(project, my_role="owner", principal=principal)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project, my_role = await require_project_role(db, project_id, principal)
    member_role, is_favorite = await _my_membership(
        db, project_id, principal.employee_id
    )
    # Гостю в ЧУЖОМ личном счётчики НЕ отдаём (15.09): членство там выдаётся
    # ради одной задачи — назначением, упоминанием или поручением, — а
    # `_task_counts` считает по ВСЕМ задачам проекта и выдал бы «37 задач, 12
    # закрыто» про чужие заметки. Задач гость не получит (`personal_task_scope`),
    # но и числа ему знать незачем. `None` клиент понимает как «не знаем» и
    # счётчик просто не рисует.
    hide_counts = personal_task_scope(project, principal) is not None
    counts = None if hide_counts else (await _task_counts(db, [project_id])).get(
        project_id, (0, 0)
    )
    return _project_to_response(
        project,
        my_role or member_role,
        is_favorite,
        principal=principal,
        counts=counts,
    )


@router.put("/projects/{project_id}/favorite", response_model=ProjectResponse)
async def set_favorite(
    project_id: UUID,
    body: ProjectFavoriteUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Личное избранное: любой участник переключает флаг на СВОЁМ членстве."""
    project, _ = await require_project_role(db, project_id, principal)
    member = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.employee_id == principal.employee_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        # hub:admin вне членства — избранное вешать не на что.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Избранное доступно только участникам проекта",
        )
    member.is_favorite = body.is_favorite
    await db.commit()
    return _project_to_response(
        project, member.role, member.is_favorite, principal=principal
    )


@router.put("/projects/{project_id}/folder", response_model=ProjectResponse)
async def set_project_folder(
    project_id: UUID,
    body: ProjectFolderAssign,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Переложить проект в папку (folder_id=null — вынуть из папки).

    Гейт owner — как у переименования: папка общая, смена видна ВСЕМ
    участникам в сайдбаре. Клиент гейтит контролы по уже существующему
    `can_manage` в ProjectResponse, новых полей не нужно.
    """
    project, _ = await require_project_role(
        db, project_id, principal, allow=("owner",)
    )
    assert_not_personal(project, action="класть в папку")
    # ИНВАРИАНТ: FK projects.folder_id НЕ проверяет совпадение тенантов —
    # RI-триггеры Postgres всегда обходят RLS. Единственная защита от
    # кросс-тенантной ссылки — это чтение через tenant-scoped сессию.
    # Никогда не присваивать folder_id без предварительного db.get.
    if body.folder_id is not None and await db.get(ProjectFolder, body.folder_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Папка не найдена"
        )
    project.folder_id = body.folder_id
    await db.commit()
    await db.refresh(project)
    # Членство перечитываем (см. комментарий в update_project): иначе
    # admin-owner теряет бейдж роли и флаг избранного сразу после переноса.
    member_role, is_favorite = await _my_membership(
        db, project_id, principal.employee_id
    )
    return _project_to_response(project, member_role, is_favorite, principal=principal)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project, _ = await require_project_role(
        db, project_id, principal, allow=EDIT_ROLES
    )
    changed: dict[str, object] = {}
    if body.name is not None and body.name != project.name:
        changed["name"] = {"old": project.name, "new": body.name}
        project.name = body.name
    if body.description is not None and body.description != project.description:
        # Только факт: 20 000 знаков в JSONB на каждую правку — не метаполе.
        changed["description"] = {"changed": True}
        project.description = body.description
    if changed:
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="update",
            object_type="project",
            object_id=project.id,
            object_label=f"{project.key} · {project.name}",
            diff=changed,
        )
    await db.commit()
    await db.refresh(project)
    # Членство перечитываем, а не берём роль из require_project_role: та отдаёт
    # None ЛЮБОМУ hub:admin (short-circuit до запроса membership), и админ-owner
    # потерял бы бейдж роли и флаг избранного сразу после правки.
    member_role, is_favorite = await _my_membership(
        db, project_id, principal.employee_id
    )
    return _project_to_response(project, member_role, is_favorite, principal=principal)


@router.post("/projects/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    from datetime import UTC, datetime

    project, _ = await require_project_role(
        db, project_id, principal, allow=("owner",)
    )
    assert_not_personal(project, action="архивировать")
    if project.archived_at is None:
        project.archived_at = datetime.now(UTC)
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="archive",
            object_type="project",
            object_id=project.id,
            object_label=f"{project.key} · {project.name}",
        )
        await db.commit()
        await db.refresh(project)
    member_role, is_favorite = await _my_membership(
        db, project_id, principal.employee_id
    )
    return _project_to_response(project, member_role, is_favorite, principal=principal)


@router.post("/projects/{project_id}/unarchive", response_model=ProjectResponse)
async def unarchive_project(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project, _ = await require_project_role(
        db, project_id, principal, allow=("owner",)
    )
    if project.archived_at is not None:
        project.archived_at = None
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.employee_id,
            action="restore",
            object_type="project",
            object_id=project.id,
            object_label=f"{project.key} · {project.name}",
        )
        await db.commit()
        await db.refresh(project)
    member_role, is_favorite = await _my_membership(
        db, project_id, principal.employee_id
    )
    return _project_to_response(project, member_role, is_favorite, principal=principal)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    key: str = Query(..., max_length=32, description="Ключ проекта — подтверждение"),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Удалить проект НАВСЕГДА, вместе со всем содержимым.

    Мягкий вариант — архивация: она уже есть и ничего не теряет. Корзины нет
    сознательно: второй предикат скрытости пришлось бы вкручивать в каждый
    кросс-проектный запрос (поиск, «Мои задачи», статистика, календарь,
    ассистент) — ровно туда, где сегодня прячется личный проект.

    `key` обязателен и проверяется СЕРВЕРОМ, хотя власти не добавляет: право
    уже проверено выше. Он закрывает другой класс багов — рассинхрон id и
    того, что человек прочитал в диалоге. Без него удаление не того проекта
    вернуло бы 204 как ни в чём не бывало.
    """
    await enforce_rate_limit(
        bucket="project:delete",
        employee_id=str(principal.employee_id),
        limit=5,
        window_sec=60,
    )
    project, _ = await require_project_role(
        db, project_id, principal, allow=("owner",)
    )
    assert_not_personal(project, action="удалить")
    if key != project.key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ключ не совпадает — проверьте, тот ли проект",
        )

    # Глобальных таймаутов в приложении нет (только в миграциях). Каскад по
    # проекту в тысячу задач трогает больше десятка таблиц и держит локи, а
    # прод крутится на ОДНОМ воркере — занятый лок обязан уронить запрос, а не
    # заморозить трекер.
    await db.execute(text("SET LOCAL lock_timeout = '5s'"))
    await db.execute(text("SET LOCAL statement_timeout = '30s'"))

    # Что снимать с диска — собираем ДО каскада: после него строк не будет.
    blob_keys = list(
        (
            await db.execute(
                select(TaskAttachment.storage_key)
                .join(Task, Task.id == TaskAttachment.task_id)
                .where(Task.project_id == project_id)
            )
        ).scalars()
    )
    if project.badge_storage_key:
        blob_keys.append(project.badge_storage_key)
    task_total = (
        await db.execute(
            select(func.count()).select_from(Task).where(Task.project_id == project_id)
        )
    ).scalar_one()

    # Журнал — в ЭТОЙ ЖЕ транзакции и ДО удаления: «нет действия без записи и
    # наоборот». `object_label` задуман ровно для этого — переживает объект.
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type="project",
        object_id=project_id,
        object_label=f"{project.key} · {project.name}",
        diff={"tasks": task_total, "attachments": len(blob_keys)},
    )
    await db.flush()  # сессия autoflush=False

    # public_share_tokens — одна из четырёх таблиц БЕЗ RLS, то есть
    # единственное место продукта, где DELETE может выйти за тенант. Явный
    # tenant_id обязателен. Подзапрос по tasks идёт под RLS и сам ограничен.
    await db.execute(
        delete(PublicShareToken).where(
            PublicShareToken.tenant_id == principal.tenant_id,
            or_(
                and_(
                    PublicShareToken.scope == "project",
                    PublicShareToken.entity_id == project_id,
                ),
                and_(
                    PublicShareToken.scope == "task",
                    PublicShareToken.entity_id.in_(
                        select(Task.id).where(Task.project_id == project_id)
                    ),
                ),
            ),
        )
    )
    # Уведомление связано с проектом только адресом (`/projects/{id}?task=…`).
    # Оставленная строка навсегда висела бы во «Входящих» и вела на 404.
    await db.execute(
        delete(Notification).where(Notification.url.like(f"/projects/{project_id}%"))
    )

    # Core DELETE, не `db.delete(project)`. У Project.members стоит
    # cascade="all, delete-orphan" с lazy="noload": ORM захотел бы загрузить
    # коллекцию, noload отдал бы пустую, дочерних DELETE не выпустилось бы — и
    # верный результат получился бы по случайности, на каскаде БД. Core-DELETE
    # делает контракт «каскадит база» явным.
    res = await db.execute(delete(Project).where(Project.id == project_id))
    if res.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Проект не найден")
    await db.commit()

    # Файлы — ПОСЛЕ commit и в отдельном потоке (см. докстринг purge_blobs).
    if blob_keys:
        await asyncio.to_thread(purge_blobs, blob_keys)

# ─── Бейдж проекта ──────────────────────────────────────────────────────────


@router.put("/projects/{project_id}/badge", response_model=ProjectResponse)
async def set_project_badge(
    project_id: UUID,
    body: ProjectBadgeUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Поставить эмодзи или снять бейдж совсем (`emoji: null` → буквы).

    Гейт — edit-tier (`EDIT_ROLES`), как у переименования: бейдж это профиль
    проекта, а не управление им. Владелец и редактор ставят его одинаково.

    Личный проект НЕ исключаем: `assert_not_personal` сторожит инвариант
    скрытости (архив, папка, публичная ссылка), а бейдж его не трогает —
    ровно как переименование, которое личному проекту разрешено намеренно.
    """
    await enforce_rate_limit(
        bucket="project:write",
        employee_id=str(principal.employee_id),
        limit=60,
        window_sec=60,
    )
    project, _ = await require_project_role(
        db, project_id, principal, allow=EDIT_ROLES
    )

    # Картинка и эмодзи взаимоисключающи (CHECK ck_projects_badge_exclusive),
    # поэтому установка эмодзи обязана снять картинку. Ключ запоминаем ДО
    # правки: после commit его уже негде взять.
    old_key = project.badge_storage_key
    project.badge_emoji = body.emoji
    project.badge_storage_key = None
    project.badge_mime = None
    await db.commit()
    await db.refresh(project)
    if old_key:
        await asyncio.to_thread(purge_blobs, [old_key])

    member_role, is_favorite = await _my_membership(
        db, project_id, principal.employee_id
    )
    return _project_to_response(project, member_role, is_favorite, principal=principal)


@router.post("/projects/{project_id}/badge/image", response_model=ProjectResponse)
async def upload_project_badge(
    project_id: UUID,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Загрузить картинку бейджа. Ставит её и снимает эмодзи."""
    await enforce_rate_limit(
        bucket="attach:upload",
        employee_id=str(principal.employee_id),
        limit=30,
        window_sec=60,
    )
    project, _ = await require_project_role(
        db, project_id, principal, allow=EDIT_ROLES
    )

    settings = get_settings()
    if check_free_space() < settings.media_min_free_bytes:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="На сервере кончилось место — обратитесь к администратору",
        )

    mime = resolve_mime(file.content_type, file.filename or "")
    if mime not in BADGE_MIME_EXT:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Бейдж — картинка PNG, JPG или WebP",
        )
    # Магические байты. У бейджа это строже, чем у вложений: вложение уходит
    # с `Content-Disposition: attachment`, а бейдж отдаётся INLINE в <img>.
    head = await file.read(SNIFF_HEAD_BYTES)
    await file.seek(0)
    if sniff_mismatch(mime, head):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Содержимое файла не соответствует заявленному типу",
        )

    storage_key = storage_key_for_badge(project.tenant_id, project.id, mime)
    dest = absolute_path(storage_key)
    dest.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > BADGE_MAX_BYTES:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Картинка больше {BADGE_MAX_BYTES // 1024} КБ",
                    )
                fh.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сохранить картинку",
        ) from exc

    # Порядок обязателен: файл записан, СТАРЫЙ ключ запомнили, строку
    # обновили, commit — и только потом сносим старый файл. Обратный порядок
    # при неудачном commit оставил бы строку, указывающую в пустоту.
    old_key = project.badge_storage_key
    project.badge_storage_key = storage_key
    project.badge_mime = mime
    project.badge_emoji = None
    try:
        await db.commit()
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    await db.refresh(project)
    if old_key:
        await asyncio.to_thread(purge_blobs, [old_key])

    member_role, is_favorite = await _my_membership(
        db, project_id, principal.employee_id
    )
    return _project_to_response(project, member_role, is_favorite, principal=principal)


@router.get("/projects/{project_id}/badge")
async def serve_project_badge(project_id: UUID, s: str = Query(..., max_length=64)):
    """Отдать картинку бейджа по подписи.

    `require_auth` НЕТ намеренно: `<img>` не несёт заголовок Authorization —
    тот же довод, что у медиа и у инструкций. Авторизует подпись, а вместе с
    ней и tenant: ключ хранения начинается с tenant_id и входит в подписанное
    сообщение.

    Нет проекта / нет бейджа / подпись не сходится — 404 во всех трёх случаях:
    зонд не должен различать «не существует» и «не та подпись».
    """
    async with tenant_scoped_session(None, bypass_rls=True) as scan:
        project = await scan.get(Project, project_id)
        if project is None or not project.badge_storage_key or not project.badge_mime:
            raise HTTPException(status_code=404, detail="Не найдено")
        storage_key, mime = project.badge_storage_key, project.badge_mime

    if not verify_badge_signature(project_id, storage_key, s):
        raise HTTPException(status_code=404, detail="Не найдено")

    settings = get_settings()
    if not settings.media_accel_enabled:
        path = absolute_path(storage_key)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Не найдено")
        return FileResponse(
            path=path, media_type=mime, content_disposition_type="inline"
        )
    return Response(
        status_code=200,
        headers={
            "X-Accel-Redirect": f"/_protected_media/{storage_key}",
            "Content-Type": mime,
            "Content-Disposition": "inline",
            # Адрес меняется вместе с картинкой (uuid в ключе), поэтому год и
            # immutable безопасны: устаревшая запись кэша никому не покажется.
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )

# ─── Members ────────────────────────────────────────────────────────────────


async def _list_members(
    db: AsyncSession, project_id: UUID
) -> list[ProjectMemberResponse]:
    """Members + JOIN shadow_users for email/full_name (active rows only)."""
    rows = await db.execute(
        select(
            ProjectMember.id,
            ProjectMember.employee_id,
            ProjectMember.role,
            ProjectMember.added_at,
            ShadowUser.email,
            ShadowUser.full_name,
        )
        .join(
            ShadowUser,
            (ShadowUser.employee_id == ProjectMember.employee_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.added_at)
    )
    return [
        ProjectMemberResponse(
            id=r.id,
            employee_id=r.employee_id,
            role=r.role,
            added_at=r.added_at,
            email=r.email,
            full_name=r.full_name,
        )
        for r in rows.all()
    ]


@router.get(
    "/projects/{project_id}/members", response_model=list[ProjectMemberResponse]
)
async def list_members(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectMemberResponse]:
    project, _role = await require_project_role(db, project_id, principal)
    # Приглашённому в ЧУЖОЕ личное — 403: состав участников личного
    # пространства это список тех, кому человек что-то поручал, то есть тот же
    # агрегат «по всем задачам», что дашборд и календарь. Карточка задачи
    # деградирует молча — она читает `members.data?.find(owner)` ради строки
    # «запросить доступ у владельца» и без ответа просто её не рисует.
    assert_full_project_access(project, principal)
    return await _list_members(db, project_id)


@router.post(
    "/projects/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    project_id: UUID,
    body: ProjectMemberAdd,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectMemberResponse:
    await require_project_role(db, project_id, principal, allow=("owner",))
    # Target employee must exist in shadow_users for this tenant (must have
    # logged into Hub at least once).
    target = await db.get(ShadowUser, body.employee_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сотрудник не найден в Hub. Попросите его сначала зайти на hub.signaris.ru.",
        )
    member = ProjectMember(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        project_id=project_id,
        employee_id=body.employee_id,
        role=body.role,
        added_by=principal.employee_id,
    )
    db.add(member)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Этот сотрудник уже в проекте",
        ) from exc
    return ProjectMemberResponse(
        id=member.id,
        employee_id=member.employee_id,
        role=member.role,  # type: ignore[arg-type]
        added_at=member.added_at,
        email=target.email,
        full_name=target.full_name,
    )


def _assert_not_personal_owner(
    project: Project, member: ProjectMember, *, action: str
) -> None:
    """Хозяина личного пространства нельзя вынести из него самого.

    Защиты «последнего owner'а» тут мало: добавив второго owner'а и удалив
    себя, человек навсегда теряет своё «Личное» — /api/me продолжает отдавать
    id, на котором GET /projects/{id} даёт 404, а секция на /my ломается.
    """
    if project.personal_owner_id == member.employee_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Владельца личного проекта нельзя {action}",
        )


@router.patch(
    "/projects/{project_id}/members/{member_id}", response_model=ProjectMemberResponse
)
async def update_member(
    project_id: UUID,
    member_id: UUID,
    body: ProjectMemberUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectMemberResponse:
    project, _ = await require_project_role(
        db, project_id, principal, allow=("owner",)
    )
    member = await db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Участник не найден")
    _assert_not_personal_owner(project, member, action="понизить в роли")
    # Last-owner protection.
    if member.role == "owner" and body.role != "owner":
        count = await db.execute(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id, ProjectMember.role == "owner"
            )
        )
        if len(count.all()) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="В проекте должен остаться хотя бы один owner",
            )
    member.role = body.role
    await db.commit()
    await db.refresh(member)
    members = await _list_members(db, project_id)
    enriched = next((m for m in members if m.id == member_id), None)
    if enriched is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось перечитать участника после обновления",
        )
    return enriched


@router.delete(
    "/projects/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    project_id: UUID,
    member_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    project, _ = await require_project_role(
        db, project_id, principal, allow=("owner",)
    )
    member = await db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Участник не найден")
    _assert_not_personal_owner(project, member, action="удалить из проекта")
    if member.role == "owner":
        count = await db.execute(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id, ProjectMember.role == "owner"
            )
        )
        if len(count.all()) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="В проекте должен остаться хотя бы один owner",
            )
    await db.delete(member)
    await db.commit()


# Ensure fetch_project_or_404 stays imported (used indirectly via require_project_role).
_ = fetch_project_or_404
