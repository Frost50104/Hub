"""Схемы зеркала реестра объектов (0053, выкат 3)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SiteMirrorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    site_id: UUID
    code: str | None
    name: str
    address: str | None
    legal_name: str | None
    inn: str | None
    email: str | None
    phone: str | None
    archived_at: datetime | None
    synced_at: datetime


class SitesResponse(BaseModel):
    items: list[SiteMirrorResponse]
    # Свежесть ВСЕГО снимка (max(synced_at) не старше фиксированных суток).
    # Протухло → карточки магазинов показывают локальные поля с меткой
    # «данные реестра устарели» — третье состояние связи.
    snapshot_fresh: bool


class PendingSiteOut(BaseModel):
    """Объект реестра без карточки магазина, который автоматика не завела
    (`registry_apply.plan_apply`): решает человек — создать или привязать."""

    site_id: UUID
    code: str | None
    name: str
    address: str | None
    iiko_ref: str | None
    reason: str  # no_iiko_ref | code_collision | name_collision
    candidate_store_id: UUID | None = None
    candidate_store_name: str | None = None


class PendingSitesResponse(BaseModel):
    items: list[PendingSiteOut]
