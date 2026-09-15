"""Task attachments API — multipart upload + streaming download + delete."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.attachment import TaskAttachment
from app.models.shadow import ShadowUser
from app.models.task import Task
from app.schemas.attachment import AttachmentResponse
from app.services.activity_writer import record_activity
from app.services.attachments import absolute_path, download_filename, store_upload
from app.services.personal_projects import require_task_access
from app.services.project_access import is_hub_admin

router = APIRouter(tags=["attachments"])


async def _fetch_task_visible(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_task_access(db, task, principal)
    return task


async def _list_enriched(db: AsyncSession, task_id: UUID) -> list[AttachmentResponse]:
    rows = await db.execute(
        select(
            TaskAttachment.id,
            TaskAttachment.task_id,
            TaskAttachment.filename,
            TaskAttachment.mime,
            TaskAttachment.size_bytes,
            TaskAttachment.uploaded_by,
            TaskAttachment.created_at,
            ShadowUser.email,
            ShadowUser.full_name,
        )
        .join(
            ShadowUser,
            (ShadowUser.employee_id == TaskAttachment.uploaded_by)
            & (ShadowUser.deleted_at.is_(None)),
            isouter=True,
        )
        .where(TaskAttachment.task_id == task_id)
        .order_by(TaskAttachment.created_at)
    )
    return [
        AttachmentResponse(
            id=r.id,
            task_id=r.task_id,
            filename=r.filename,
            mime=r.mime,
            size_bytes=r.size_bytes,
            uploaded_by=r.uploaded_by,
            created_at=r.created_at,
            uploader_email=r.email,
            uploader_full_name=r.full_name,
        )
        for r in rows.all()
    ]


@router.get(
    "/tasks/{task_id}/attachments", response_model=list[AttachmentResponse]
)
async def list_attachments(
    task_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[AttachmentResponse]:
    await _fetch_task_visible(db, task_id, principal)
    return await _list_enriched(db, task_id)


@router.post(
    "/tasks/{task_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    task_id: UUID,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> AttachmentResponse:
    await enforce_rate_limit(
        bucket="attach:upload",
        employee_id=str(principal.employee_id),
        limit=30,
        window_sec=60,
    )
    task = await _fetch_task_visible(db, task_id, principal)
    # Edit-permission required — uploading mutates a task.
    await require_task_access(
        db, task, principal, allow=("owner", "editor")
    )

    attachment = await store_upload(
        file,
        tenant_id=task.tenant_id,
        task_id=task.id,
        uploaded_by=principal.employee_id,
    )
    db.add(attachment)
    await db.flush()
    await record_activity(
        db,
        tenant_id=task.tenant_id,
        task_id=task.id,
        actor_id=principal.employee_id,
        kind="attached",
        payload={
            "attachment_id": str(attachment.id),
            "filename": attachment.filename,
            "size_bytes": attachment.size_bytes,
        },
    )
    await db.commit()
    out = await _list_enriched(db, task.id)
    matching = next((a for a in out if a.id == attachment.id), None)
    if matching is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось перечитать вложение",
        )
    return matching


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    attachment = await db.get(TaskAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    # Reuse task-visibility guard.
    task = await db.get(Task, attachment.task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    await require_task_access(db, task, principal)

    path = absolute_path(attachment.storage_key)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="Файл на диске отсутствует"
        )
    return FileResponse(
        path=path,
        media_type=attachment.mime,
        # Имена, испорченные прежним ASCII-санитайзером (в БД лежит голое
        # «docx»), чиним на отдаче: без расширения Windows файл не открывает.
        filename=download_filename(
            attachment.filename, mime=attachment.mime, fallback="вложение"
        ),
    )


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    attachment = await db.get(TaskAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    task = await db.get(Task, attachment.task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    # Uploader can always delete. Otherwise need owner/editor in the project,
    # or hub:admin (covered by require_project_role(allow=owner,editor)).
    if attachment.uploaded_by != principal.employee_id and not is_hub_admin(principal):
        await require_task_access(
            db, task, principal, allow=("owner", "editor")
        )

    path = absolute_path(attachment.storage_key)
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass  # We still drop the DB row — orphans get cleaned by a future sweeper.

    await record_activity(
        db,
        tenant_id=task.tenant_id,
        task_id=task.id,
        actor_id=principal.employee_id,
        kind="unattached",
        payload={"attachment_id": str(attachment.id), "filename": attachment.filename},
    )
    await db.delete(attachment)
    await db.commit()


# Keep shutil alive — used elsewhere in storage cleanup paths (future).
_ = shutil
_ = Path
