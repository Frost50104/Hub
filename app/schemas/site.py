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
