"""Pydantic-схемы тестов (Ф3b).

Структуры options/answer по qtype — см. app/models/quiz.py. Валидация
жёсткая на входе builder'а: битый вопрос не должен попасть в снапшоты.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuestionDraft(BaseModel):
    qtype: str = Field(pattern="^(single|multi|open|match|order)$")
    prompt: str = Field(min_length=1, max_length=2000)
    media_id: UUID | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    answer: dict[str, Any] | None = None
    points: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def _validate_structure(self) -> QuestionDraft:
        if self.qtype in ("single", "multi"):
            opts = self.options.get("options")
            if not isinstance(opts, list) or not (2 <= len(opts) <= 10):
                raise ValueError("Вариантов должно быть от 2 до 10")
            if any(not isinstance(o, str) or not o.strip() for o in opts):
                raise ValueError("Пустой вариант ответа")
            correct = (self.answer or {}).get("correct")
            if not isinstance(correct, list) or not correct:
                raise ValueError("Отметьте правильный ответ")
            if any(not isinstance(i, int) or not 0 <= i < len(opts) for i in correct):
                raise ValueError("Индекс правильного ответа вне диапазона")
            if self.qtype == "single" and len(correct) != 1:
                raise ValueError("У одиночного выбора ровно один правильный ответ")
            if len(set(correct)) != len(correct):
                raise ValueError("Дубли в правильных ответах")
        elif self.qtype == "match":
            left = self.options.get("left")
            right = self.options.get("right")
            if (
                not isinstance(left, list)
                or not isinstance(right, list)
                or not (2 <= len(left) <= 8)
                or len(right) != len(left)
            ):
                raise ValueError("Сопоставление: от 2 до 8 пар, колонки равной длины")
            pairs = (self.answer or {}).get("pairs")
            if not isinstance(pairs, list) or len(pairs) != len(left):
                raise ValueError("Задайте соответствие для каждой пары")
            lefts = [p[0] for p in pairs if isinstance(p, list) and len(p) == 2]
            rights = [p[1] for p in pairs if isinstance(p, list) and len(p) == 2]
            if sorted(lefts) != list(range(len(left))) or sorted(rights) != list(
                range(len(left))
            ):
                raise ValueError("Соответствие должно покрывать все элементы без дублей")
        elif self.qtype == "order":
            items = self.options.get("items")
            if not isinstance(items, list) or not (2 <= len(items) <= 10):
                raise ValueError("Порядок: от 2 до 10 элементов")
            if any(not isinstance(o, str) or not o.strip() for o in items):
                raise ValueError("Пустой элемент списка")
        return self


class QuizUpsert(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="draft", pattern="^(draft|published)$")
    pass_score_pct: int = Field(default=80, ge=1, le=100)
    attempts_limit: int | None = Field(default=None, ge=1, le=50)
    shuffle_questions: bool = False
    shuffle_options: bool = True
    show_correct_answers: bool = True
    is_required: bool = True
    questions: list[QuestionDraft] = Field(default_factory=list, max_length=100)


class QuestionFull(BaseModel):
    """Вопрос для builder'а (с ответами)."""

    id: UUID
    position: int
    qtype: str
    prompt: str
    media_id: UUID | None
    media_url: str | None = None
    options: dict[str, Any]
    answer: dict[str, Any] | None
    points: int


class QuizManageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_id: UUID
    lesson_id: UUID | None
    title: str
    description: str | None
    status: str
    pass_score_pct: int
    attempts_limit: int | None
    shuffle_questions: bool
    shuffle_options: bool
    show_correct_answers: bool
    is_required: bool
    questions: list[QuestionFull] = []


class QuizConsumerResponse(BaseModel):
    """Мета теста + моё состояние (без вопросов — они в попытке)."""

    id: UUID
    lesson_id: UUID | None
    title: str
    description: str | None
    pass_score_pct: int
    attempts_limit: int | None
    is_required: bool
    show_correct_answers: bool
    question_count: int
    attempts_used: int
    best_score_pct: int | None = None
    passed: bool = False
    pending_review: bool = False
    active_attempt_id: UUID | None = None
    can_start: bool = True


class SnapshotQuestion(BaseModel):
    """Вопрос попытки, санитизированный (без answer)."""

    id: str
    qtype: str
    prompt: str
    media_id: str | None = None
    media_url: str | None = None
    options: dict[str, Any]
    points: int


class AttemptResponse(BaseModel):
    id: UUID
    quiz_id: UUID
    attempt_no: int
    questions: list[SnapshotQuestion]
    answers: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None
    score_pct: int | None
    passed: bool | None
    needs_review: bool
    # После сабмита: qid → верно/неверно (None = на ручной проверке).
    results: dict[str, bool | None] | None = None
    # Правильные ответы (только если quiz.show_correct_answers и сдано).
    correct_answers: dict[str, Any] | None = None


class AnswerBody(BaseModel):
    question_id: str = Field(max_length=64)
    value: Any = None


class ReviewBody(BaseModel):
    scores: dict[str, float] = Field(default_factory=dict)


class ReviewQueueItem(BaseModel):
    attempt_id: UUID
    quiz_id: UUID
    quiz_title: str
    course_id: UUID
    profile_id: UUID
    employee_name: str
    finished_at: datetime | None
    open_question_count: int


class ResetAttemptsBody(BaseModel):
    profile_id: UUID


class RatingRow(BaseModel):
    profile_id: UUID
    full_name: str
    position_name: str | None = None
    store_name: str | None = None
    points: float
    rank: int
    is_me: bool = False


class RatingResponse(BaseModel):
    period: str
    scope: str
    rows: list[RatingRow]
    me: RatingRow | None = None
    total_participants: int
