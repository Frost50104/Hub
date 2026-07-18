"""Integration-тесты Ф3b: попытки, review-flow, замок after_prev_test,
идемпотентность activity_events и сертификатов."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.courses import complete_lesson, get_lesson
from app.api.quizzes import (
    review_attempt,
    save_answer,
    start_or_resume_attempt,
    submit_attempt,
    upsert_lesson_quiz,
)
from app.models.activity import ActivityEvent, Certificate
from app.models.notification import Notification
from app.schemas.quiz import AnswerBody, QuestionDraft, QuizUpsert, ReviewBody
from app.services.certificate import issue_if_earned
from app.services.points import award
from tests.integration.test_courses import _mk_course, _mk_member

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_redis_no_push(monkeypatch):
    async def _noop_rate_limit(**kw) -> None:
        return None

    from app.api import courses as courses_api
    from app.api import quizzes as quizzes_api
    from app.services import notify_batch

    monkeypatch.setattr(quizzes_api, "enforce_rate_limit", _noop_rate_limit)
    monkeypatch.setattr(courses_api, "enforce_rate_limit", _noop_rate_limit)
    monkeypatch.setattr(notify_batch, "_schedule_push_batch", lambda **kw: None)


async def _mk_publisher(db: AsyncSession, tenant_id: uuid.UUID):
    principal, profile = await _mk_member(db, tenant_id, email="hr@t.ru")
    profile.content_role = "publisher"
    await db.flush()
    return principal, profile


def _single_draft(correct: int = 1) -> QuestionDraft:
    return QuestionDraft(
        qtype="single",
        prompt="2 + 2?",
        options={"options": ["3", "4"]},
        answer={"correct": [correct]},
    )


def _open_draft() -> QuestionDraft:
    return QuestionDraft(qtype="open", prompt="Опишите стандарт приветствия", points=2)


async def _publish_quiz(db, principal, lesson_id, questions, **kw):
    body = QuizUpsert(
        title=kw.pop("title", "Тест урока"),
        status="published",
        pass_score_pct=kw.pop("pass_score_pct", 80),
        attempts_limit=kw.pop("attempts_limit", None),
        shuffle_questions=False,
        shuffle_options=False,
        questions=questions,
        **kw,
    )
    return await upsert_lesson_quiz(lesson_id, body, principal, db)


async def test_attempt_lifecycle_and_limit(db: AsyncSession, tenant_id: uuid.UUID):
    hr, _ = await _mk_publisher(db, tenant_id)
    member, profile = await _mk_member(db, tenant_id)
    _course, lessons = await _mk_course(db, tenant_id, lesson_count=1)

    quiz = await _publish_quiz(
        db, hr, lessons[0].id, [_single_draft(correct=1)], attempts_limit=2
    )

    attempt = await start_or_resume_attempt(quiz.id, member, db)
    assert attempt.attempt_no == 1
    # Санитизация: вопрос попытки не содержит правильного ответа.
    assert not hasattr(attempt.questions[0], "answer")
    qid = attempt.questions[0].id

    # Резюм: повторный старт возвращает ту же попытку.
    again = await start_or_resume_attempt(quiz.id, member, db)
    assert again.id == attempt.id

    await save_answer(attempt.id, AnswerBody(question_id=qid, value=0), member, db)
    submitted = await submit_attempt(attempt.id, member, db)
    assert submitted.score_pct == 0 and submitted.passed is False
    # Провал события не даёт (фильтр по профилю: testcontainers-юзер —
    # superuser, RLS-изоляции между тестами нет).
    count = (
        await db.execute(
            select(func.count())
            .select_from(ActivityEvent)
            .where(ActivityEvent.profile_id == profile.id)
        )
    ).scalar_one()
    assert count == 0

    # Попытка 2 — верный ответ.
    attempt2 = await start_or_resume_attempt(quiz.id, member, db)
    assert attempt2.attempt_no == 2
    await save_answer(attempt2.id, AnswerBody(question_id=qid, value=1), member, db)
    submitted2 = await submit_attempt(attempt2.id, member, db)
    assert submitted2.score_pct == 100 and submitted2.passed is True
    assert submitted2.correct_answers  # show_correct_answers=True

    # События: passed (по retry-весу) + perfect_bonus, идемпотентно.
    events = (
        (await db.execute(select(ActivityEvent).where(ActivityEvent.profile_id == profile.id)))
        .scalars()
        .all()
    )
    kinds = sorted(e.event_type for e in events)
    assert kinds == ["quiz.passed", "quiz.perfect_bonus"]
    passed_event = next(e for e in events if e.event_type == "quiz.passed")
    assert passed_event.meta["attempt_no"] == 2
    assert float(passed_event.points) == 0.5  # вес quiz.passed_retry

    # Лимит 2 исчерпан → 409.
    with pytest.raises(HTTPException) as exc:
        await start_or_resume_attempt(quiz.id, member, db)
    assert exc.value.status_code == 409


async def test_review_flow_blocks_and_finalizes(db: AsyncSession, tenant_id: uuid.UUID):
    hr, _hr_profile = await _mk_publisher(db, tenant_id)
    member, profile = await _mk_member(db, tenant_id, email="seller2@t.ru")
    _course, lessons = await _mk_course(db, tenant_id, lesson_count=1)

    quiz = await _publish_quiz(
        db, hr, lessons[0].id, [_single_draft(correct=0), _open_draft()], pass_score_pct=60
    )

    attempt = await start_or_resume_attempt(quiz.id, member, db)
    closed_id = next(q.id for q in attempt.questions if q.qtype == "single")
    open_id = next(q.id for q in attempt.questions if q.qtype == "open")
    await save_answer(attempt.id, AnswerBody(question_id=closed_id, value=0), member, db)
    await save_answer(
        attempt.id,
        AnswerBody(question_id=open_id, value="Приветствуем в течение 10 секунд"),
        member,
        db,
    )
    submitted = await submit_attempt(attempt.id, member, db)

    # До проверки: нет score/passed/событий, новая попытка запрещена.
    assert submitted.needs_review is True
    assert submitted.score_pct is None and submitted.passed is None
    assert submitted.correct_answers is None  # разбор скрыт до проверки
    assert (
        await db.execute(
            select(func.count())
            .select_from(ActivityEvent)
            .where(ActivityEvent.profile_id == profile.id)
        )
    ).scalar_one() == 0
    with pytest.raises(HTTPException) as exc:
        await start_or_resume_attempt(quiz.id, member, db)
    assert exc.value.status_code == 409

    # HR-уведомление ушло НАШЕМУ publisher'у. Количество не ассертим:
    # testcontainers-юзер — superuser, RLS не режет кросс-тестовых
    # publisher'ов в реестре получателей (на проде их отрежет RLS).
    review_notif = (
        await db.execute(
            select(Notification).where(
                Notification.kind == "quiz.review_needed",
                Notification.payload["attempt_id"].astext == str(attempt.id),
                Notification.employee_id == hr.employee_id,
            )
        )
    ).scalars().all()
    assert len(review_notif) == 1

    # Проверка: 2 из 2 баллов за open → (1+2)/3 = 100%.
    reviewed = await review_attempt(
        attempt.id, ReviewBody(scores={open_id: 2}), hr, db
    )
    assert reviewed.score_pct == 100 and reviewed.passed is True
    assert reviewed.needs_review is False

    events = (
        (await db.execute(select(ActivityEvent).where(ActivityEvent.profile_id == profile.id)))
        .scalars()
        .all()
    )
    assert sorted(e.event_type for e in events) == ["quiz.passed", "quiz.perfect_bonus"]

    # Сотруднику ушло quiz.reviewed.
    reviewed_notif = (
        await db.execute(
            select(Notification).where(
                Notification.kind == "quiz.reviewed",
                Notification.payload["quiz_id"].astext == str(quiz.id),
            )
        )
    ).scalars().all()
    assert len(reviewed_notif) == 1

    # Повторное ревью → 409.
    with pytest.raises(HTTPException) as exc:
        await review_attempt(attempt.id, ReviewBody(scores={}), hr, db)
    assert exc.value.status_code == 409


async def test_after_prev_test_lock(db: AsyncSession, tenant_id: uuid.UUID):
    hr, _ = await _mk_publisher(db, tenant_id)
    member, _profile = await _mk_member(db, tenant_id, email="seller3@t.ru")
    course, lessons = await _mk_course(db, tenant_id, lesson_count=2)
    lessons[1].unlock_rule = "after_prev_test"
    await db.flush()

    quiz = await _publish_quiz(db, hr, lessons[0].id, [_single_draft(correct=1)])

    # Урок 1 завершён, но тест не сдан → урок 2 всё ещё заперт.
    await get_lesson(lessons[0].id, member, db)
    await complete_lesson(lessons[0].id, member, db)
    with pytest.raises(HTTPException) as exc:
        await get_lesson(lessons[1].id, member, db)
    assert exc.value.status_code == 403

    # Сдал тест → урок 2 открыт.
    attempt = await start_or_resume_attempt(quiz.id, member, db)
    qid = attempt.questions[0].id
    await save_answer(attempt.id, AnswerBody(question_id=qid, value=1), member, db)
    await submit_attempt(attempt.id, member, db)
    resp = await get_lesson(lessons[1].id, member, db)
    assert resp.id == lessons[1].id


async def test_lesson_event_and_certificate_idempotent(
    db: AsyncSession, tenant_id: uuid.UUID
):
    member, profile = await _mk_member(db, tenant_id, email="seller4@t.ru")
    course, lessons = await _mk_course(
        db, tenant_id, lesson_count=1, certificate_enabled=True
    )
    await get_lesson(lessons[0].id, member, db)
    await complete_lesson(lessons[0].id, member, db)

    events = (
        (
            await db.execute(
                select(ActivityEvent).where(
                    ActivityEvent.profile_id == profile.id,
                    ActivityEvent.event_type == "lesson.completed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1 and float(events[0].points) == 1.0

    certs = (
        (await db.execute(select(Certificate).where(Certificate.profile_id == profile.id)))
        .scalars()
        .all()
    )
    assert len(certs) == 1
    assert certs[0].course_title == course.title
    assert certs[0].serial.startswith("HUB-")

    # Повторная выдача/начисление — идемпотентны.
    assert await issue_if_earned(db, course, profile) is False
    assert (
        await award(
            db,
            tenant_id=tenant_id,
            profile_id=profile.id,
            event_type="lesson.completed",
            object_type="course_lesson",
            object_id=lessons[0].id,
        )
        is False
    )


async def test_reset_attempts_unblocks(db: AsyncSession, tenant_id: uuid.UUID):
    from app.api.quizzes import reset_attempts
    from app.schemas.quiz import ResetAttemptsBody

    hr, _ = await _mk_publisher(db, tenant_id)
    member, profile = await _mk_member(db, tenant_id, email="seller5@t.ru")
    _course, lessons = await _mk_course(db, tenant_id, lesson_count=1)
    quiz = await _publish_quiz(
        db, hr, lessons[0].id, [_single_draft(correct=1)], attempts_limit=1
    )

    attempt = await start_or_resume_attempt(quiz.id, member, db)
    qid = attempt.questions[0].id
    await save_answer(attempt.id, AnswerBody(question_id=qid, value=0), member, db)
    await submit_attempt(attempt.id, member, db)
    with pytest.raises(HTTPException):
        await start_or_resume_attempt(quiz.id, member, db)

    await reset_attempts(quiz.id, ResetAttemptsBody(profile_id=profile.id), hr, db)
    fresh = await start_or_resume_attempt(quiz.id, member, db)
    assert fresh.attempt_no == 1
