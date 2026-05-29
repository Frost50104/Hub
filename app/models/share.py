"""Public share tokens — view-only deep-links (3.6.12)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PublicShareToken(Base):
    __tablename__ = "public_share_tokens"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('task','project')",
            name="ck_public_share_tokens_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    token: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, unique=True, default=uuid4
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
