"""Рейтинг активности + сертификаты (Ф3b, ТЗ §7/§4.5).

- activity_events — append-only (RLS SELECT+INSERT, как audit_log).
  Partial-unique (tenant, profile, event_type, object_type, object_id)
  гарантирует «первое действие»: повторное прохождение/переигрывание не
  дублирует баллы. points — СНАПШОТ веса на момент события (правка весов
  в настройках не пересчитывает историю — так и задумано).
- certificates — выдаются при завершении курса с certificate_enabled;
  снапшот названий/имён (переименование курса не меняет выданный
  сертификат), serial уникален в tenant'е.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ACTIVITY_EVENT_TYPES = (
    "lesson.completed",
    "quiz.passed",
    "quiz.perfect_bonus",
    "material.acknowledged",
    "news.acknowledged",
    "survey.completed",
    "product.first_view",
    "login.daily",
)


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    points: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False, index=True
    )


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (
        UniqueConstraint("course_id", "profile_id", name="uq_certificates_course_profile"),
        UniqueConstraint("tenant_id", "serial", name="uq_certificates_serial"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    serial: Mapped[str] = mapped_column(String(32), nullable=False)
    course_title: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
