"""Настройки learn-домена — singleton per tenant, JSONB.

Ключи (аддитивно, дефолты в `app/services/learn_settings.py`):
- inactivity_*: пороги/тексты правила «90 дней неактивности»;
- rating_weights: веса activity-событий (Ф3b);
- survey_k_anonymity: порог K анонимных опросов (Ф2, дефолт 5);
- media-лимиты/квоты (Ф3a).

Обновление — ТОЛЬКО по-ключево через jsonb_set (сервис), не перезаписью
всего JSONB: два админа, правящие разные ключи, не должны затирать друг
друга (last-writer-wins по ключу, не по документу).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LearningSettings(Base):
    __tablename__ = "learning_settings"

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )
