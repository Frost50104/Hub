"""Pydantic schemas for Project + ProjectMember endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ProjectRole = Literal["owner", "editor", "viewer"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # When omitted, backend generates a unique key from `name` (initials,
    # cyrillic transliteration, collision check). Clients may pass an
    # explicit key (e.g. importing from Asana) — same format constraints.
    key: str | None = Field(
        default=None, min_length=1, max_length=32, pattern=r"^[A-Z][A-Z0-9_-]*$"
    )
    description: str | None = Field(default=None, max_length=4000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    description: str | None
    archived_at: datetime | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    my_role: ProjectRole | None = None  # filled from project_members for current principal
    is_favorite: bool = False  # личное избранное текущего пользователя
    # Эффективные права вызывающего = членство ИЛИ hub:admin-байпас. Считает
    # ТОЛЬКО сервер (project_access.capabilities) — клиент их рендерит и своей
    # копии правила не заводит. Без дефолтов: забытый call-site должен падать
    # на валидации, а не молча прятать контролы.
    can_edit: bool  # секции create/rename, задачи, публичные ссылки, метки на задаче
    can_manage: bool  # удаление секций, кастом-поля, CRUD меток, участники, архив
    # Эффективные права вызывающего = членство ИЛИ hub:admin-байпас. Считает
    # ТОЛЬКО сервер: клиент не знает про байпас и, дублируя правило у себя,
    # уже разошёлся с бэкендом (админ вне членства видел проект read-only).
    can_edit: bool = False  # создавать/переименовывать секции, править задачи
    can_manage: bool = False  # удалять секции, поля, участники, архив


class ProjectFavoriteUpdate(BaseModel):
    is_favorite: bool


class ProjectMemberAdd(BaseModel):
    employee_id: UUID
    role: ProjectRole


class ProjectMemberUpdate(BaseModel):
    role: ProjectRole


class ProjectMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID
    role: ProjectRole
    added_at: datetime
    # Enriched from shadow_users JOIN — may be null if the row was reaped.
    email: str | None = None
    full_name: str | None = None
