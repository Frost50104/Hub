"""Тесты уроков/курсов (Ф3b, ТЗ §4.2-4.4).

- Quiz привязан к уроку (lesson_id) ИЛИ к курсу целиком (lesson_id NULL =
  финальный тест). status draft|published — без полного lifecycle (тест не
  самостоятельный контент, живёт внутри курса).
- QuizQuestion.options/answer — JSONB, структура зависит от qtype:
  single|multi: options={"options": [...]}, answer={"correct": [idx, ...]}
  match:        options={"left": [...], "right": [...]}, answer={"pairs": [[l, r], ...]}
  order:        options={"items": [...]}, answer=None (правильный порядок =
                порядок items; предъявляется перемешанным)
  open:         options={}, answer=None (ручная проверка HR)
- QuizAttempt: UNIQUE(quiz_id, profile_id, attempt_no); снапшот вопросов
  (как предъявлены: порядок + shuffle по seed) живёт в попытке — правка
  вопросов не ломает начатые/сданные попытки, HR ревьюит снапшот.
  Лимит попыток считается по finished_at IS NOT NULL — обрыв связи не
  сжигает попытку (резюм с тем же seed/снапшотом).
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

QUESTION_TYPES = ("single", "multi", "open", "match", "order")


class Quiz(Base):
    __tablename__ = "quizzes"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published')", name="ck_quizzes_status"),
        CheckConstraint(
            "pass_score_pct >= 1 AND pass_score_pct <= 100", name="ck_quizzes_pass_score"
        ),
        # Один тест на урок (финальных тестов курса тоже один — частичный
        # уникальный индекс в миграции).
        UniqueConstraint("lesson_id", name="uq_quizzes_lesson"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    # Ровно один владелец: курс (тест урока/финальный) ИЛИ кампания
    # аттестации (Ф8) — CHECK в миграции 0030.
    course_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_campaigns.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    lesson_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("course_lessons.id", ondelete="CASCADE"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'draft'")
    )
    pass_score_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("80")
    )
    attempts_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL = ∞
    shuffle_questions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    shuffle_options: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    show_correct_answers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Обязательный тест гейтит after_prev_test-замок следующего урока.
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
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


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (
        CheckConstraint(
            "qtype IN ('single', 'multi', 'open', 'match', 'order')",
            name="ck_quiz_questions_qtype",
        ),
        CheckConstraint("points >= 1", name="ck_quiz_questions_points"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    quiz_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    qtype: Mapped[str] = mapped_column(String(8), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # «Вопрос по фото/видео» — media_files + подписанные URL (Ф3a).
    media_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        UniqueConstraint(
            "quiz_id", "profile_id", "attempt_no", name="uq_quiz_attempts_no"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    quiz_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    # Снапшот вопросов КАК ПРЕДЪЯВЛЕНЫ (с правильными ответами — для
    # скоринга и HR-ревью; потребителю отдаётся санитизированная копия).
    snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # {question_id: value} — автосохранение per-question.
    answers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Ручная проверка открытых вопросов (ТЗ: HR): до неё passed/score NULL.
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    review_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("shadow_users.employee_id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
