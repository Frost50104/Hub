"""Pydantic schemas for task attachments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    filename: str
    mime: str
    size_bytes: int
    uploaded_by: UUID
    created_at: datetime
    # Enriched via JOIN shadow_users (optional — may be null if reaped).
    uploader_email: str | None = None
    uploader_full_name: str | None = None
    # Подписанный адрес для тега <video>; заполняется ТОЛЬКО у video/*.
    # Одиночные ручки (загрузка, удаление) его тоже отдают — поле собирает
    # общий `_list_enriched`, другого пути в ответ у вложения нет.
    preview_url: str | None = None
