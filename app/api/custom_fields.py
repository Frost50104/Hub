"""Custom fields API — per-project field definitions + per-task values (3.6.10).

Permissions:
- GET definitions / GET values    → viewer+ on project (any project member)
- POST/PATCH/DELETE definition    → owner only (or hub:admin)
- PUT/DELETE value                → editor+ on project (owner or editor)

Definition order is `position` NUMERIC (LexoRank-like). New definitions go
to the tail; reorder = PATCH with new position. Value-shape validation is
delegated to `app.services.custom_field_validator`.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.custom_field import CustomFieldDefinition, TaskCustomFieldValue
from app.models.shadow import ShadowUser
from app.models.task import Task
from app.schemas.custom_field import (
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionResponse,
    CustomFieldDefinitionUpdate,
    CustomFieldValueResponse,
    CustomFieldValueSet,
)
from app.services.custom_field_validator import (
    CustomFieldValueError,
)
from app.services.custom_field_validator import (
    validate as validate_value,
)
from app.services.project_access import require_project_role

router = APIRouter(tags=["custom_fields"])


async def _next_position(db: AsyncSession, project_id: UUID) -> Decimal:
    row = await db.execute(
        select(
            func.coalesce(func.max(CustomFieldDefinition.position) + 1, 1)
        ).where(CustomFieldDefinition.project_id == project_id)
    )
    return Decimal(row.scalar_one())


# ─── Definitions ────────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/custom-fields",
    response_model=list[CustomFieldDefinitionResponse],
)
async def list_custom_fields(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[CustomFieldDefinitionResponse]:
    await require_project_role(db, project_id, principal)
    rows = await db.execute(
        select(CustomFieldDefinition)
        .where(CustomFieldDefinition.project_id == project_id)
        .order_by(CustomFieldDefinition.position)
    )
    return [
        CustomFieldDefinitionResponse.model_validate(d) for d in rows.scalars().all()
    ]


@router.post(
    "/projects/{project_id}/custom-fields",
    response_model=CustomFieldDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_custom_field(
    project_id: UUID,
    body: CustomFieldDefinitionCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CustomFieldDefinitionResponse:
    await require_project_role(db, project_id, principal, allow=("owner",))

    if body.type in ("select", "multi_select") and not body.options:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Для типов select/multi_select требуется минимум одна опция",
        )

    # Unique name check — DB also enforces via UNIQUE(project_id, name),
    # but a friendly 422 beats raw IntegrityError.
    existing = await db.execute(
        select(CustomFieldDefinition.id).where(
            CustomFieldDefinition.project_id == project_id,
            CustomFieldDefinition.name == body.name,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Поле «{body.name}» уже существует в этом проекте",
        )

    definition = CustomFieldDefinition(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        project_id=project_id,
        name=body.name,
        type=body.type,
        options=[opt.model_dump() for opt in body.options],
        position=await _next_position(db, project_id),
    )
    db.add(definition)
    await db.commit()
    await db.refresh(definition)
    return CustomFieldDefinitionResponse.model_validate(definition)


@router.patch(
    "/projects/{project_id}/custom-fields/{field_id}",
    response_model=CustomFieldDefinitionResponse,
)
async def update_custom_field(
    project_id: UUID,
    field_id: UUID,
    body: CustomFieldDefinitionUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CustomFieldDefinitionResponse:
    await require_project_role(db, project_id, principal, allow=("owner",))

    definition = await db.get(CustomFieldDefinition, field_id)
    if definition is None or definition.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Поле не найдено"
        )

    if body.name is not None and body.name != definition.name:
        clash = await db.execute(
            select(CustomFieldDefinition.id).where(
                CustomFieldDefinition.project_id == project_id,
                CustomFieldDefinition.name == body.name,
                CustomFieldDefinition.id != field_id,
            )
        )
        if clash.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Поле «{body.name}» уже существует",
            )
        definition.name = body.name

    if body.options is not None:
        if definition.type in ("select", "multi_select") and not body.options:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Нельзя оставить select без опций",
            )
        definition.options = [opt.model_dump() for opt in body.options]

    if body.position is not None:
        definition.position = body.position

    await db.commit()
    await db.refresh(definition)
    return CustomFieldDefinitionResponse.model_validate(definition)


@router.delete(
    "/projects/{project_id}/custom-fields/{field_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_custom_field(
    project_id: UUID,
    field_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_project_role(db, project_id, principal, allow=("owner",))
    definition = await db.get(CustomFieldDefinition, field_id)
    if definition is None or definition.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Поле не найдено"
        )
    # ON DELETE CASCADE on task_custom_field_values handles the rows.
    await db.delete(definition)
    await db.commit()


# ─── Per-task values ────────────────────────────────────────────────────────


async def _fetch_task_visible(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена"
        )
    await require_project_role(db, task.project_id, principal)
    return task


@router.get(
    "/tasks/{task_id}/custom-fields",
    response_model=list[CustomFieldValueResponse],
)
async def list_task_custom_values(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[CustomFieldValueResponse]:
    await _fetch_task_visible(db, task_id, principal)
    rows = await db.execute(
        select(TaskCustomFieldValue).where(TaskCustomFieldValue.task_id == task_id)
    )
    return [CustomFieldValueResponse.model_validate(v) for v in rows.scalars().all()]


@router.get(
    "/projects/{project_id}/custom-field-values",
    response_model=list[CustomFieldValueResponse],
)
async def list_project_custom_values(
    project_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[CustomFieldValueResponse]:
    """Batch endpoint — every value for every task in this project.

    Avoids N+1 when the List view renders custom-field columns. The total
    payload is bounded by `defs.count × tasks.count`, both manageable for
    Hub-scale projects (≤ thousands of tasks, ≤ tens of fields).
    """
    await require_project_role(db, project_id, principal)
    rows = await db.execute(
        select(TaskCustomFieldValue)
        .join(Task, Task.id == TaskCustomFieldValue.task_id)
        .where(Task.project_id == project_id)
    )
    return [CustomFieldValueResponse.model_validate(v) for v in rows.scalars().all()]


@router.put(
    "/tasks/{task_id}/custom-fields/{field_id}",
    response_model=CustomFieldValueResponse,
)
async def set_task_custom_value(
    task_id: UUID,
    field_id: UUID,
    body: CustomFieldValueSet,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CustomFieldValueResponse:
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )

    task = await _fetch_task_visible(db, task_id, principal)
    await require_project_role(
        db, task.project_id, principal, allow=("owner", "editor")
    )

    definition = await db.get(CustomFieldDefinition, field_id)
    if definition is None or definition.project_id != task.project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Поле не найдено в этом проекте",
        )

    try:
        validated = validate_value(definition, body.value)
    except CustomFieldValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from None

    # `person` type: verify the employee exists in shadow_users (tenant-scoped
    # via RLS — looking up an outsider returns None even with a valid UUID).
    if definition.type == "person" and validated is not None:
        target = await db.get(ShadowUser, UUID(validated))
        if target is None or target.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Сотрудник не найден в Hub",
            )

    await db.execute(
        pg_insert(TaskCustomFieldValue)
        .values(
            task_id=task.id,
            field_id=field_id,
            tenant_id=task.tenant_id,
            value=validated,
        )
        .on_conflict_do_update(
            index_elements=["task_id", "field_id"],
            set_={"value": validated},
        )
    )
    await db.commit()
    saved = await db.get(TaskCustomFieldValue, (task.id, field_id))
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сохранить значение",
        )
    return CustomFieldValueResponse.model_validate(saved)


@router.delete(
    "/tasks/{task_id}/custom-fields/{field_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_task_custom_value(
    task_id: UUID,
    field_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    task = await _fetch_task_visible(db, task_id, principal)
    await require_project_role(
        db, task.project_id, principal, allow=("owner", "editor")
    )
    row = await db.get(TaskCustomFieldValue, (task.id, field_id))
    if row is not None:
        await db.delete(row)
        await db.commit()
