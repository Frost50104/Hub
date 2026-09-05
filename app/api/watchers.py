"""Task watchers API: само-подписка + редакторское управление составом (02.09).

Добавление ДРУГОГО человека — выдача доступа: не-участник получает
viewer-членство (`ensure_project_member`, зеркало исполнителей — иначе пуши
вели бы его в 404). Членство при снятии наблюдателя НЕ отзывается — та же
семантика, что у снятия исполнителя.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from signaris_auth import Principal
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.shadow import ShadowUser
from app.models.task import Task, TaskWatcher
from app.schemas.watcher import WatcherAddBody, WatcherResponse
from app.services.activity_writer import record_activity
from app.services.personal_projects import require_task_access
from app.services.project_access import ensure_project_member

router = APIRouter(tags=["watchers"])


async def _fetch_task_visible(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_task_access(db, task, principal)
    return task


@router.get("/tasks/{task_id}/watchers", response_model=list[WatcherResponse])
async def list_watchers(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[WatcherResponse]:
    await _fetch_task_visible(db, task_id, principal)
    rows = await db.execute(
        select(
            TaskWatcher.employee_id,
            TaskWatcher.added_reason,
            TaskWatcher.added_at,
            ShadowUser.email,
            ShadowUser.full_name,
        )
        .join(
            ShadowUser,
            (ShadowUser.employee_id == TaskWatcher.employee_id)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(TaskWatcher.task_id == task_id)
        .order_by(TaskWatcher.added_at)
    )
    return [
        WatcherResponse(
            employee_id=r.employee_id,
            added_reason=r.added_reason,
            added_at=r.added_at,
            email=r.email,
            full_name=r.full_name,
        )
        for r in rows.all()
    ]


@router.post(
    "/tasks/{task_id}/watchers/me",
    response_model=WatcherResponse,
    status_code=status.HTTP_201_CREATED,
)
async def join_watching(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> WatcherResponse:
    task = await _fetch_task_visible(db, task_id, principal)
    result = await db.execute(
        pg_insert(TaskWatcher)
        .values(
            task_id=task.id,
            employee_id=principal.employee_id,
            tenant_id=task.tenant_id,
            added_reason="manual",
        )
        .on_conflict_do_nothing(index_elements=["task_id", "employee_id"])
    )
    # Лента — только при реальной вставке: повторный клик по колокольчику
    # добавлял строку «подписался» при каждом нажатии.
    if (result.rowcount or 0) > 0:
        await record_activity(
            db,
            tenant_id=task.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="watcher_added",
        )
    await db.commit()
    me_row = await db.execute(
        select(ShadowUser.email, ShadowUser.full_name).where(
            ShadowUser.employee_id == principal.employee_id
        )
    )
    me = me_row.first()
    row = await db.execute(
        select(TaskWatcher.added_reason, TaskWatcher.added_at).where(
            TaskWatcher.task_id == task.id,
            TaskWatcher.employee_id == principal.employee_id,
        )
    )
    rec = row.first()
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось перечитать watcher",
        )
    return WatcherResponse(
        employee_id=principal.employee_id,
        added_reason=rec.added_reason,
        added_at=rec.added_at,
        email=me.email if me else None,
        full_name=me.full_name if me else None,
    )


@router.delete(
    "/tasks/{task_id}/watchers/me", status_code=status.HTTP_204_NO_CONTENT
)
async def leave_watching(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    task = await _fetch_task_visible(db, task_id, principal)
    result = await db.execute(
        delete(TaskWatcher).where(
            TaskWatcher.task_id == task.id,
            TaskWatcher.employee_id == principal.employee_id,
        )
    )
    if (result.rowcount or 0) > 0:
        await record_activity(
            db,
            tenant_id=task.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="watcher_removed",
        )
    await db.commit()


@router.post(
    "/tasks/{task_id}/watchers",
    response_model=WatcherResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_watcher(
    task_id: UUID,
    body: WatcherAddBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> WatcherResponse:
    """Редактор подписывает ДРУГОГО человека (02.09) — зеркало assignee-ручки.

    Не-участник получает viewer-членство ВСЕГДА (даже если watcher-строка уже
    была — легаси после переноса могла остаться без членства): пуши по задаче
    идут без проверки видимости, и подписка без доступа вела бы в 404.
    Идемпотентно; лента — только при реальной вставке.
    """
    await enforce_rate_limit(
        bucket="task:write",
        employee_id=str(principal.employee_id),
        limit=120,
        window_sec=60,
    )
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_task_access(db, task, principal, allow=("owner", "editor"))

    target_row = await db.execute(
        select(ShadowUser.email, ShadowUser.full_name).where(
            ShadowUser.employee_id == body.employee_id,
            ShadowUser.deleted_at.is_(None),
        )
    )
    target = target_row.first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сотрудник не найден")

    result = await db.execute(
        pg_insert(TaskWatcher)
        .values(
            task_id=task.id,
            employee_id=body.employee_id,
            tenant_id=task.tenant_id,
            added_reason="manual",
        )
        .on_conflict_do_nothing(index_elements=["task_id", "employee_id"])
    )
    await ensure_project_member(
        db,
        project_id=task.project_id,
        tenant_id=task.tenant_id,
        employee_id=body.employee_id,
        added_by=principal.employee_id,
    )
    if (result.rowcount or 0) > 0 and body.employee_id != principal.employee_id:
        await record_activity(
            db,
            tenant_id=task.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="watcher_added",
            payload={
                "employee_id": str(body.employee_id),
                "name": target.full_name or target.email,
            },
        )
    await db.commit()

    rec_row = await db.execute(
        select(TaskWatcher.added_reason, TaskWatcher.added_at).where(
            TaskWatcher.task_id == task.id,
            TaskWatcher.employee_id == body.employee_id,
        )
    )
    rec = rec_row.first()
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось перечитать watcher",
        )
    return WatcherResponse(
        employee_id=body.employee_id,
        added_reason=rec.added_reason,
        added_at=rec.added_at,
        email=target.email,
        full_name=target.full_name,
    )


@router.delete(
    "/tasks/{task_id}/watchers/{employee_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_watcher(
    task_id: UUID,
    employee_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Редактор снимает наблюдателя. Членство НЕ отзывается (как у исполнителей)."""
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_task_access(db, task, principal, allow=("owner", "editor"))
    name_row = await db.execute(
        select(ShadowUser.full_name, ShadowUser.email).where(
            ShadowUser.employee_id == employee_id
        )
    )
    named = name_row.first()
    result = await db.execute(
        delete(TaskWatcher).where(
            TaskWatcher.task_id == task.id,
            TaskWatcher.employee_id == employee_id,
        )
    )
    if (result.rowcount or 0) > 0:
        await record_activity(
            db,
            tenant_id=task.tenant_id,
            task_id=task.id,
            actor_id=principal.employee_id,
            kind="watcher_removed",
            payload=(
                {
                    "employee_id": str(employee_id),
                    "name": (named.full_name or named.email) if named else None,
                }
                if employee_id != principal.employee_id
                else None
            ),
        )
    await db.commit()
