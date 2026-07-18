"""Курсы и уроки (Ф3a, ТЗ §4-5): каталог, конструктор, режимы прохождения.

- Курс — ContentLifecycleMixin + audience. Видимость потребителю =
  audience OR активное назначение (adversarial-ревью §8).
- Урок — TipTap-JSON (content_format=blocks) ИЛИ готовый PDF
  (content_format=pdf, media_id). У урока свой мини-статус draft/published —
  уроки готовятся внутри опубликованного курса.
- Режимы (ТЗ §4.1): sequential (урок открывается после завершения
  предыдущего), free (все открыты), mixed (unlock_rule на уроке решает).
  Замки проверяются НА СЕРВЕРЕ (GET урока → 403 locked) с монотонностью:
  урок с существующим прогрессом не запирается задним числом.
- MediaFile — загруженные медиа уроков (фото/видео/PDF), отдача только
  через подписанные URL (`app/services/learn_media.py`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ContentLifecycleMixin

COURSE_TYPES = ("mandatory", "recommended", "career", "info")
PROGRESSION_MODES = ("sequential", "free", "mixed")
UNLOCK_RULES = ("inherit", "free", "after_prev_test")
MEDIA_KINDS = ("image", "video", "pdf")


class Course(ContentLifecycleMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'review', 'published', 'archived')",
            name="ck_courses_status",
        ),
        CheckConstraint(
            "course_type IN ('mandatory', 'recommended', 'career', 'info')",
            name="ck_courses_type",
        ),
        CheckConstraint(
            "progression_mode IN ('sequential', 'free', 'mixed')",
            name="ck_courses_progression",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    audience_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audiences.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    course_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'info'")
    )
    progression_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'sequential'")
    )
    # Сертификат выдаётся в Ф3b — поле заведено сразу.
    certificate_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )


class CourseLesson(Base):
    __tablename__ = "course_lessons"
    __table_args__ = (
        CheckConstraint(
            "content_format IN ('blocks', 'pdf')", name="ck_course_lessons_format"
        ),
        CheckConstraint(
            "unlock_rule IN ('inherit', 'free', 'after_prev_test')",
            name="ck_course_lessons_unlock",
        ),
        CheckConstraint(
            "status IN ('draft', 'published')", name="ck_course_lessons_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    course_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    content_format: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'blocks'")
    )
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # PDF-урок (ТЗ §5.3): готовый файл вместо блоков.
    pdf_media_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    forbid_download: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    unlock_rule: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'inherit'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'draft'")
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


class LessonTemplate(Base):
    """Шаблон урока (ТЗ §5.6) — сохранённый content-JSON."""

    __tablename__ = "lesson_templates"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class MediaFile(Base):
    __tablename__ = "media_files"
    __table_args__ = (
        CheckConstraint("kind IN ('image', 'video', 'pdf')", name="ck_media_files_kind"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
