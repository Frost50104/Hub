"""Аттестации персонала (Ф8, ТЗ §20) — кампании поверх движка тестов.

Кампания владеет СВОИМ quiz (quizzes.campaign_id; вопросы можно
импортировать из тестов уроков). Попытки/скоринг/ревью открытых ответов —
существующий механизм Ф3b: снапшот вопросов в попытке уже даёт «версию»
аттестации на момент прохождения.

Статусы: draft → active (аудитория уведомлена, окно starts/ends) → closed.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

CAMPAIGN_STATUSES = ("draft", "active", "closed")


class AssessmentCampaign(Base):
    __tablename__ = "assessment_campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'closed')",
            name="ck_assessment_campaigns_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audiences.id", ondelete="SET NULL"),
        nullable=True,
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'draft'"), index=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )
