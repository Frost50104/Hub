"""Гейт «тест предыдущего урока сдан» (Ф3b) для замка after_prev_test."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quiz import Quiz, QuizAttempt


async def passed_required_quiz_lessons(
    db: AsyncSession, course_id: UUID, profile_id: UUID
) -> dict[UUID, bool]:
    """lesson_id → пройден ли его required-квиз (уроки без квиза не входят)."""
    quizzes = (
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
    if not quizzes:
        return {}
    quiz_by_lesson = {q.lesson_id: q.id for q in quizzes}
    passed_quiz_ids = {
        r[0]
        for r in await db.execute(
            select(QuizAttempt.quiz_id).where(
                QuizAttempt.quiz_id.in_(quiz_by_lesson.values()),
                QuizAttempt.profile_id == profile_id,
                QuizAttempt.passed.is_(True),
            )
        )
    }
    return {
        lesson_id: quiz_id in passed_quiz_ids
        for lesson_id, quiz_id in quiz_by_lesson.items()
    }
