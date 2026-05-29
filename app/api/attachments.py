"""Task attachments API — multipart upload + streaming download + delete."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.attachment import TaskAttachment
from app.models.shadow import ShadowUser
from app.models.task import Task
from app.schemas.attachment import AttachmentResponse
from app.services.activity_writer import record_activity
from app.services.attachments import ALLOWED_MIME, absolute_path, storage_key_for
from app.services.project_access import is_hub_admin, require_project_role

router = APIRouter(tags=["attachments"])


async def _fetch_task_visible(
    db: AsyncSession, task_id: UUID, principal: Principal
) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await require_project_role(db, task.project_id, principal)
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
    await require_project_role(
        db, task.project_id, principal, allow=("owner", "editor")
    )

    settings = get_settings()
    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Тип файла {mime!r} не разрешён",
        )

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Имя файла обязательно"
        )

    storage_key, sanitized_name = storage_key_for(task.tenant_id, task.id, file.filename)
    dest = absolute_path(storage_key)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Stream to disk in chunks. Reject as soon as we exceed the limit so a
    # giant upload doesn't waste disk.
    max_bytes = settings.attachment_max_bytes
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
        # Make sure partial files don't linger.
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сохранить файл",
        ) from exc

    attachment = TaskAttachment(
        id=uuid4(),
        tenant_id=task.tenant_id,
        task_id=task.id,
        uploaded_by=principal.employee_id,
        filename=sanitized_name,
        mime=mime,
        size_bytes=written,
        storage_key=storage_key,
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
            "filename": sanitized_name,
            "size_bytes": written,
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
    await require_project_role(db, task.project_id, principal)

    path = absolute_path(attachment.storage_key)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="Файл на диске отсутствует"
        )
    return FileResponse(
        path=path,
        media_type=attachment.mime,
        filename=attachment.filename,
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
        await require_project_role(
            db, task.project_id, principal, allow=("owner", "editor")
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
