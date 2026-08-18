"""Схемы папок проектов (ОС 17.08)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProjectFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ProjectFolderUpdate(BaseModel):
    """Переименование. Порядок меняется отдельной ручкой /reorder."""

    name: str = Field(min_length=1, max_length=255)


class ProjectFolderReorder(BaseModel):
    folder_ids: list[UUID]


class ProjectFolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    position: int
    created_at: datetime


class ProjectFolderListResponse(BaseModel):
    """Не голый list: при НУЛЕ папок флаг прав негде взять, и кнопка «Новая
    папка» не показалась бы никогда. Права считает ТОЛЬКО сервер (инвариант
    CLAUDE.md), клиент их рендерит.

    `project_count` здесь СОЗНАТЕЛЬНО нет: он был бы tenant-wide и расходился
    бы с тем, что пользователь реально видит («Маркетинг · 7», а внутри 2),
    плюс утечка «есть проекты, которые тебе не показывают». Считает клиент по
    уже отфильтрованному членством списку.
    """

    folders: list[ProjectFolderResponse]
    can_manage: bool
