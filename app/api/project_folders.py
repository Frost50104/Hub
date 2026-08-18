"""CRUD папок проектов (ОС 17.08).

Отдельный префикс `/project-folders`, а не `/projects/folders`: последний
разрешался бы только порядком регистрации относительно `/projects/{project_id}`
и ломался бы от перестановки декораторов. Прецедент в проекте — секции живут
на верхнеуровневом `/sections/{id}`.

Никаких `WHERE tenant_id = ...` — RLS делает это сама, поэтому чужая папка
недостижима: `db.get` вернёт None → 404.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.project_folder import ProjectFolder
from app.schemas.project_folder import (
    ProjectFolderCreate,
    ProjectFolderListResponse,
    ProjectFolderReorder,
    ProjectFolderResponse,
    ProjectFolderUpdate,
)
from app.services.project_access import can_manage_project_folders

router = APIRouter(tags=["project-folders"])

_DUPLICATE = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="Папка с таким названием уже есть",
)
_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Папка не найдена"
)


def _require_manage(principal: Principal) -> None:
    if not can_manage_project_folders(principal):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Управление папками доступно только admin/member ролям в Hub",
        )


async def _ordered(db: AsyncSession) -> list[ProjectFolder]:
    # position без UNIQUE — tie-break по имени держит порядок стабильным.
    rows = await db.execute(
        select(ProjectFolder).order_by(
            ProjectFolder.position, func.lower(ProjectFolder.name)
        )
    )
    return list(rows.scalars().all())


@router.get("/project-folders", response_model=ProjectFolderListResponse)
async def list_project_folders(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectFolderListResponse:
    """Все папки тенанта видны любому hub-юзеру, включая viewer'а.

    Фильтровать «только непустые для меня» нельзя: свежесозданная папка пуста
    по определению, и её нельзя было бы выбрать в «Переместить в папку».
    """
    folders = await _ordered(db)
    return ProjectFolderListResponse(
        folders=[ProjectFolderResponse.model_validate(f) for f in folders],
        can_manage=can_manage_project_folders(principal),
    )


@router.post(
    "/project-folders",
    response_model=ProjectFolderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_folder(
    body: ProjectFolderCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectFolderResponse:
    _require_manage(principal)
    next_position = (
        await db.execute(
            select(func.coalesce(func.max(ProjectFolder.position) + 1, 0))
        )
    ).scalar_one()
    folder = ProjectFolder(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        name=body.name,
        position=next_position,
        created_by=principal.employee_id,
    )
    db.add(folder)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _DUPLICATE from exc
    await db.refresh(folder)
    return ProjectFolderResponse.model_validate(folder)


@router.put("/project-folders/reorder", response_model=list[ProjectFolderResponse])
async def reorder_project_folders(
    body: ProjectFolderReorder,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectFolderResponse]:
    """Полный список id в новом порядке → position 0..n-1.

    Никаких сдвигов и deferred-констрейнтов: уникальности на position нет.
    Чужие id отфильтрует RLS, неизвестные молча игнорируются.
    """
    _require_manage(principal)
    by_id = {f.id: f for f in await _ordered(db)}
    for idx, folder_id in enumerate(body.folder_ids):
        folder = by_id.get(folder_id)
        if folder is not None:
            folder.position = idx
    await db.commit()
    return [ProjectFolderResponse.model_validate(f) for f in await _ordered(db)]


@router.patch("/project-folders/{folder_id}", response_model=ProjectFolderResponse)
async def update_project_folder(
    folder_id: UUID,
    body: ProjectFolderUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> ProjectFolderResponse:
    _require_manage(principal)
    folder = await db.get(ProjectFolder, folder_id)
    if folder is None:
        raise _NOT_FOUND
    folder.name = body.name
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _DUPLICATE from exc
    await db.refresh(folder)
    return ProjectFolderResponse.model_validate(folder)


@router.delete("/project-folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_folder(
    folder_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Проекты НЕ удаляются: FK ON DELETE SET NULL переводит их в «Без папки»."""
    _require_manage(principal)
    folder = await db.get(ProjectFolder, folder_id)
    if folder is None:
        raise _NOT_FOUND
    await db.delete(folder)
    await db.commit()
