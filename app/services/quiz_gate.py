"""Гейт обязательного теста урока (Ф3b, ОС 2026-08).

`Quiz.is_required` — единственный источник истины: опубликованный обязательный
тест урока N, который не сдан, блокирует (а) завершение урока N
(`complete_lesson` → 409) и тем самым (б) следующий урок в sequential/mixed
(предыдущий не завершён). `unlock_rule='after_prev_test'` остаётся как
дополнительный замок (тест добавили после того, как урок уже завершили).

Состояние теста для профиля выводится ОДНОЙ функцией `derive_quiz_state` —
её же использует `consumer_quiz_state` в API, чтобы гейт и раннер не
разошлись.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quiz import Quiz, QuizAttempt

QuizGateState = Literal[
    "none",  # у урока нет обязательного опубликованного теста
    "not_started",
    "in_progress",
    "failed",
    "pending_review",
    "limit_exhausted",
    "passed",
]

# Тексты 409 для complete_lesson и подписи под кнопкой «Завершить урок».
QUIZ_GATE_MESSAGES: dict[str, str] = {
    "not_started": "Сдайте тест урока",
    "in_progress": "Закончите тест урока",
    "failed": "Сдайте тест урока",
    "pending_review": "Тест на проверке — завершить урок можно после проверки",
    "limit_exhausted": "Лимит попыток теста исчерпан — обратитесь к руководителю",
}


def derive_quiz_state(
    attempts: Iterable[QuizAttempt], attempts_limit: int | None
) -> QuizGateState:
    """Состояние обязательного теста по попыткам профиля.

    Порядок важен: passed → pending_review → in_progress → limit_exhausted →
    failed → not_started. Попытка с open-вопросами до проверки — `passed IS
    NULL` и `needs_review` → «на проверке», не «сдан».
    """
    attempts = list(attempts)
    finished = [a for a in attempts if a.finished_at is not None]
    if any(a.passed is True for a in finished):
        return "passed"
    if any(a.needs_review and a.reviewed_at is None for a in finished):
        return "pending_review"
    if any(a.finished_at is None for a in attempts):
        return "in_progress"
    if attempts_limit is not None and len(finished) >= attempts_limit:
        return "limit_exhausted"
    if finished:
        return "failed"
    return "not_started"


async def _required_quizzes(db: AsyncSession, course_id: UUID) -> list[Quiz]:
    return list(
        (
            await db.execute(
                select(Quiz).where(
                    Quiz.course_id == course_id,
                    Quiz.lesson_id.is_not(None),
                    Quiz.is_required.is_(True),
                    Quiz.status == "published",
                )
            )
        )
        .scalars()
        .all()
    )


async def required_quiz_states(
    db: AsyncSession, course_id: UUID, profile_id: UUID
) -> dict[UUID, QuizGateState]:
    """lesson_id → состояние его обязательного теста (уроки без теста не входят)."""
    quizzes = await _required_quizzes(db, course_id)
    if not quizzes:
        return {}
    by_quiz: dict[UUID, list[QuizAttempt]] = {q.id: [] for q in quizzes}
    rows = (
        await db.execute(
            select(QuizAttempt).where(
                QuizAttempt.quiz_id.in_(by_quiz.keys()),
                QuizAttempt.profile_id == profile_id,
            )
        )
    ).scalars()
    for attempt in rows:
        by_quiz[attempt.quiz_id].append(attempt)
    return {
        q.lesson_id: derive_quiz_state(by_quiz[q.id], q.attempts_limit)
        for q in quizzes
        if q.lesson_id is not None
    }


async def passed_required_quiz_lessons(
    db: AsyncSession, course_id: UUID, profile_id: UUID
) -> dict[UUID, bool]:
    """lesson_id → пройден ли его required-квиз (уроки без квиза не входят)."""
    states = await required_quiz_states(db, course_id, profile_id)
    return {lesson_id: state == "passed" for lesson_id, state in states.items()}


async def lesson_quiz_state(
    db: AsyncSession, lesson_id: UUID, profile_id: UUID | None
) -> tuple[bool, QuizGateState]:
    """(есть ли обязательный опубликованный тест, его состояние) для одного урока.
    Без профиля (менеджер без карточки) — «not_started», если тест есть."""
    quiz = (
        await db.execute(
            select(Quiz).where(
                Quiz.lesson_id == lesson_id,
                Quiz.is_required.is_(True),
                Quiz.status == "published",
            )
        )
    ).scalar_one_or_none()
    if quiz is None:
        return False, "none"
    if profile_id is None:
        return True, "not_started"
    attempts = (
        await db.execute(
            select(QuizAttempt).where(
                QuizAttempt.quiz_id == quiz.id, QuizAttempt.profile_id == profile_id
            )
        )
    ).scalars()
    return True, derive_quiz_state(attempts, quiz.attempts_limit)
