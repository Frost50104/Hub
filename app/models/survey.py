"""Опросы (Ф2, ТЗ §13): eNPS, пульс, анонимные.

Анти-деанон архитектура (adversarial-ревью плана §18-20):
- `survey_participations` — ТОЛЬКО факт участия (повторное прохождение,
  response rate); submitted_at здесь точный;
- `survey_answer_sets` — ответы с ДЕМОГРАФИЧЕСКИМ СНАПШОТОМ на момент
  ответа (перевод сотрудника не портит исторические срезы), БЕЗ timestamp
  (тайминг-деанон при одном ответе в день) и без FK на participation;
  `profile_id` заполняется ТОЛЬКО у неанонимных опросов;
- агрегаты — исключительно через `app/services/survey_stats.py`
  (k-anonymity, срезы по одному измерению за раз).

`is_anonymous` замораживается при публикации (менять нельзя).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
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

SURVEY_KINDS = ("standard", "enps", "pulse")
QUESTION_TYPES = ("single", "multi", "open", "scale", "enps")


class Survey(ContentLifecycleMixin, Base):
    __tablename__ = "surveys"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'review', 'published', 'archived')",
            name="ck_surveys_status",
        ),
        CheckConstraint(
            "kind IN ('standard', 'enps', 'pulse')", name="ck_surveys_kind"
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
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'standard'"))
    is_anonymous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )


class SurveyQuestion(Base):
    __tablename__ = "survey_questions"
    __table_args__ = (
        CheckConstraint(
            "qtype IN ('single', 'multi', 'open', 'scale', 'enps')",
            name="ck_survey_questions_qtype",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    survey_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("surveys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    qtype: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt: Mapped[str] = mapped_column(String(1000), nullable=False)
    # single/multi: {"options": ["…", …]}; scale: {"min": 1, "max": 5}.
    options: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class SurveyParticipation(Base):
    """Факт участия — отдельно от ответов (анонимность)."""

    __tablename__ = "survey_participations"

    survey_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("surveys.id", ondelete="CASCADE"),
        primary_key=True,
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class SurveyAnswerSet(Base):
    """Комплект ответов. НИКАКОГО timestamp и связи с participation."""

    __tablename__ = "survey_answer_sets"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    survey_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("surveys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Только для НЕанонимных опросов.
    profile_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Демографический снапшот на момент ответа (для срезов).
    position_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    store_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    franchisee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    department_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    org_role: Mapped[str | None] = mapped_column(String(32), nullable=True)


class SurveyAnswer(Base):
    __tablename__ = "survey_answers"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    answer_set_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("survey_answer_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("survey_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # single: {"option": i}; multi: {"options": [i,…]}; open: {"text": "…"};
    # scale/enps: {"value": n}.
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
