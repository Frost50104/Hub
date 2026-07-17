"""Общие миксины контентных моделей learn-домена (Ф1+).

`ContentLifecycleMixin` — единый lifecycle всего контента (ТЗ §25/§26):
статусы draft → review → published → archived, владелец (≠ автор, отвечает
за актуальность), период актуализации с напоминанием. Переходы — ТОЛЬКО
через `app/services/lifecycle.py` (guard'ы + audit + поисковый индекс).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

CONTENT_STATUSES = ("draft", "review", "published", "archived")


class ContentLifecycleMixin:
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'draft'"), index=True
    )

    @declared_attr
    def owner_id(cls) -> Mapped[UUID | None]:  # noqa: N805
        return mapped_column(
            PGUUID(as_uuid=True),
            ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        )

    @declared_attr
    def created_by(cls) -> Mapped[UUID | None]:  # noqa: N805
        return mapped_column(
            PGUUID(as_uuid=True),
            ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
            nullable=True,
        )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Период актуализации (ТЗ §8.2/§26): 0/NULL — не напоминать.
    review_period_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
