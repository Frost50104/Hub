"""Тесты + рейтинг + сертификаты API (Ф3b, ТЗ §4.2-4.5/§7).

Инварианты:
- лимит попыток считается по finished_at IS NOT NULL: обрыв связи не
  сжигает попытку — незавершённая возобновляется с тем же снапшотом/seed;
- правильные ответы живут ТОЛЬКО в снапшоте попытки на сервере; потребителю
  уходит санитизированная копия, разбор — после сдачи и только при
  show_correct_answers;
- open-вопросы → needs_review: passed/score/события НЕ выставляются до
  ручной проверки (HR), новые попытки заблокированы;
- события рейтинга идемпотентны (points.award, «первое действие»).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from signaris_auth import Principal
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.courses import (
    _course_visible_to,
    _get_course_or_404,
    _get_lesson_or_404,
    _require_manage,
)
from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.activity import Certificate
from app.models.employee_profile import EmployeeProfile
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.schemas.quiz import (
    AnswerBody,
    AttemptResponse,
    QuestionFull,
    QuizConsumerResponse,
    QuizManageResponse,
    QuizUpsert,
    RatingResponse,
    RatingRow,
    ResetAttemptsBody,
    ReviewBody,
    ReviewQueueItem,
    SnapshotQuestion,
)
from app.services import audit, lifecycle, points
from app.services.content_access import require_content_role, resolve_content_role
from app.services.learn_media import sign_media_path
from app.services.learn_notify import _employee_ids
from app.services.notify_batch import notify_many
from app.services.org_scope import get_profile
from app.services.quiz_scoring import (
    build_snapshot,
    finalize,
    sanitize_snapshot,
    score_attempt,
)

router = APIRouter(tags=["learn-quizzes"])


# ─── Хелперы ─────────────────────────────────────────────────────────────────


async def _get_quiz_or_404(db: AsyncSession, quiz_id: UUID) -> Quiz:
    quiz = await db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Тест не найден")
    return quiz


async def _get_attempt_or_404(db: AsyncSession, attempt_id: UUID) -> QuizAttempt:
    attempt = await db.get(QuizAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Попытка не найдена")
    return attempt


def _snapshot_questions(snapshot: list[dict]) -> list[SnapshotQuestion]:
    out = []
    for q in sanitize_snapshot(snapshot):
        media_id = q.get("media_id")
        out.append(
            SnapshotQuestion(
                id=q["id"],
                qtype=q["qtype"],
                prompt=q["prompt"],
                media_id=media_id,
                media_url=sign_media_path(UUID(media_id)) if media_id else None,
                options=q.get("options") or {},
                points=int(q.get("points") or 1),
            )
        )
    return out


def _attempt_response(
    quiz: Quiz, attempt: QuizAttempt, *, with_results: bool = False
) -> AttemptResponse:
    results = None
    correct_answers = None
    if with_results and attempt.finished_at is not None:
        scored = score_attempt(attempt.snapshot, attempt.answers)
        results = dict(scored.per_question)
        if attempt.review_scores:
            # После ревью open-вопросы получают вердикт по баллам HR.
            by_id = {q["id"]: float(q.get("points") or 1) for q in attempt.snapshot}
            for qid, score in attempt.review_scores.items():
                if qid in by_id:
                    results[qid] = float(score) >= by_id[qid]
        if quiz.show_correct_answers and not (
            attempt.needs_review and attempt.reviewed_at is None
        ):
            correct_answers = {
                q["id"]: q.get("answer") for q in attempt.snapshot if q.get("answer")
            }
    return AttemptResponse(
        id=attempt.id,
        quiz_id=attempt.quiz_id,
        attempt_no=attempt.attempt_no,
        questions=_snapshot_questions(attempt.snapshot),
        answers=attempt.answers,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        score_pct=attempt.score_pct,
        passed=attempt.passed,
        needs_review=attempt.needs_review and attempt.reviewed_at is None,
        results=results,
        correct_answers=correct_answers,
    )


async def _quiz_manager(
    db: AsyncSession, principal: Principal, quiz: Quiz
) -> lifecycle.ContentRole:
    role = await require_content_role(db, principal, "author")
    course = await _get_course_or_404(db, quiz.course_id)
    _require_manage(course, principal, role)
    return role


# ─── Builder (manager) ───────────────────────────────────────────────────────


@router.put("/learn/lessons/{lesson_id}/quiz", response_model=QuizManageResponse)
async def upsert_lesson_quiz(
    lesson_id: UUID,
    body: QuizUpsert,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> QuizManageResponse:
    role = await require_content_role(db, principal, "author")
    lesson = await _get_lesson_or_404(db, lesson_id)
    course = await _get_course_or_404(db, lesson.course_id)
    _require_manage(course, principal, role)

    if body.status == "published" and not body.questions:
        raise HTTPException(status_code=422, detail="Добавьте хотя бы один вопрос")

    quiz = (
        await db.execute(select(Quiz).where(Quiz.lesson_id == lesson_id))
    ).scalar_one_or_none()
    if quiz is None:
        quiz = Quiz(
            tenant_id=course.tenant_id,
            course_id=course.id,
            lesson_id=lesson_id,
            title=body.title,
            created_by=principal.employee_id,
        )
        db.add(quiz)
        await db.flush()
        action = "create"
    else:
        action = "update"

    quiz.title = body.title
    quiz.description = body.description
    quiz.status = body.status
    quiz.pass_score_pct = body.pass_score_pct
    quiz.attempts_limit = body.attempts_limit
    quiz.shuffle_questions = body.shuffle_questions
    quiz.shuffle_options = body.shuffle_options
    quiz.show_correct_answers = body.show_correct_answers
    quiz.is_required = body.is_required

    # Replace вопросов: попытки хранят собственный снапшот — история цела.
    await db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id))
    for i, draft in enumerate(body.questions):
        db.add(
            QuizQuestion(
                tenant_id=quiz.tenant_id,
                quiz_id=quiz.id,
                position=i,
                qtype=draft.qtype,
                prompt=draft.prompt,
                media_id=draft.media_id,
                options=draft.options,
                answer=draft.answer,
                points=draft.points,
            )
        )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action=action,
        object_type="quiz",
        object_id=quiz.id,
        object_label=f"{course.title} / {quiz.title}",
    )
    await db.commit()
    return await _manage_response(db, quiz)


async def _manage_response(db: AsyncSession, quiz: Quiz) -> QuizManageResponse:
    questions = (
        (
            await db.execute(
                select(QuizQuestion)
                .where(QuizQuestion.quiz_id == quiz.id)
                .order_by(QuizQuestion.position)
            )
        )
        .scalars()
        .all()
    )
    resp = QuizManageResponse.model_validate(quiz)
    resp.questions = [
        QuestionFull(
            id=q.id,
            position=q.position,
            qtype=q.qtype,
            prompt=q.prompt,
            media_id=q.media_id,
            media_url=sign_media_path(q.media_id) if q.media_id else None,
            options=q.options,
            answer=q.answer,
            points=q.points,
        )
        for q in questions
    ]
    return resp


@router.delete("/learn/quizzes/{quiz_id}", status_code=204)
async def delete_quiz(
    quiz_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    quiz = await _get_quiz_or_404(db, quiz_id)
    await _quiz_manager(db, principal, quiz)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type="quiz",
        object_id=quiz.id,
        object_label=quiz.title,
    )
    await db.delete(quiz)
    await db.commit()


@router.post("/learn/quizzes/{quiz_id}/reset-attempts", status_code=204)
async def reset_attempts(
    quiz_id: UUID,
    body: ResetAttemptsBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Разблокировать тупик «исчерпал лимит и не сдал»: publisher стирает
    попытки сотрудника по тесту (+audit). Баллы рейтинга не отзываются."""
    await require_content_role(db, principal, "publisher")
    quiz = await _get_quiz_or_404(db, quiz_id)
    result = await db.execute(
        delete(QuizAttempt).where(
            QuizAttempt.quiz_id == quiz_id, QuizAttempt.profile_id == body.profile_id
        )
    )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="quiz",
        object_id=quiz.id,
        object_label=quiz.title,
        diff={"reset_attempts_for": {"old": None, "new": str(body.profile_id)}},
    )
    await db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="Попыток не найдено")


# ─── Consumer ────────────────────────────────────────────────────────────────


@router.get("/learn/lessons/{lesson_id}/quiz")
async def get_lesson_quiz(
    lesson_id: UUID,
    manage: bool = Query(default=False),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> QuizManageResponse | QuizConsumerResponse | None:
    lesson = await _get_lesson_or_404(db, lesson_id)
    course = await _get_course_or_404(db, lesson.course_id)
    role = await resolve_content_role(db, principal)
    profile = await get_profile(db, principal)
    if not await _course_visible_to(
        db, course, principal, role, profile.id if profile else None
    ):
        raise HTTPException(status_code=404, detail="Урок не найден")

    quiz = (
        await db.execute(select(Quiz).where(Quiz.lesson_id == lesson_id))
    ).scalar_one_or_none()

    if manage:
        if quiz is None:
            return None
        await _quiz_manager(db, principal, quiz)
        return await _manage_response(db, quiz)

    if quiz is None or quiz.status != "published":
        return None

    question_count = (
        await db.execute(
            select(func.count()).select_from(QuizQuestion).where(
                QuizQuestion.quiz_id == quiz.id
            )
        )
    ).scalar_one()

    resp = QuizConsumerResponse(
        id=quiz.id,
        lesson_id=quiz.lesson_id,
        title=quiz.title,
        description=quiz.description,
        pass_score_pct=quiz.pass_score_pct,
        attempts_limit=quiz.attempts_limit,
        is_required=quiz.is_required,
        show_correct_answers=quiz.show_correct_answers,
        question_count=question_count,
        attempts_used=0,
    )
    if profile is None:
        return resp

    attempts = (
        (
            await db.execute(
                select(QuizAttempt).where(
                    QuizAttempt.quiz_id == quiz.id,
                    QuizAttempt.profile_id == profile.id,
                )
            )
        )
        .scalars()
        .all()
    )
    finished = [a for a in attempts if a.finished_at is not None]
    active = next((a for a in attempts if a.finished_at is None), None)
    scored = [a.score_pct for a in finished if a.score_pct is not None]
    resp.attempts_used = len(finished)
    resp.best_score_pct = max(scored) if scored else None
    resp.passed = any(a.passed for a in finished)
    resp.pending_review = any(
        a.needs_review and a.reviewed_at is None for a in finished
    )
    resp.active_attempt_id = active.id if active else None
    resp.can_start = (
        not resp.pending_review
        and (quiz.attempts_limit is None or len(finished) < quiz.attempts_limit)
    ) or active is not None
    return resp


@router.post("/learn/quizzes/{quiz_id}/attempts", response_model=AttemptResponse)
async def start_or_resume_attempt(
    quiz_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> AttemptResponse:
    await enforce_rate_limit(
        bucket="quiz:attempt",
        employee_id=str(principal.employee_id),
        limit=30,
        window_sec=60,
    )
    quiz = await _get_quiz_or_404(db, quiz_id)
    if quiz.status != "published":
        raise HTTPException(status_code=404, detail="Тест не найден")
    course = await _get_course_or_404(db, quiz.course_id)
    role = await resolve_content_role(db, principal)
    profile = await get_profile(db, principal)
    if profile is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    if not await _course_visible_to(db, course, principal, role, profile.id):
        raise HTTPException(status_code=404, detail="Тест не найден")

    attempts = (
        (
            await db.execute(
                select(QuizAttempt)
                .where(
                    QuizAttempt.quiz_id == quiz_id,
                    QuizAttempt.profile_id == profile.id,
                )
                .order_by(QuizAttempt.attempt_no)
            )
        )
        .scalars()
        .all()
    )
    # Резюм: незавершённая попытка возвращается как есть (тот же снапшот).
    active = next((a for a in attempts if a.finished_at is None), None)
    if active is not None:
        return _attempt_response(quiz, active)

    if any(a.needs_review and a.reviewed_at is None for a in attempts):
        raise HTTPException(
            status_code=409, detail="Предыдущая попытка ещё на проверке"
        )
    finished_count = sum(1 for a in attempts if a.finished_at is not None)
    if quiz.attempts_limit is not None and finished_count >= quiz.attempts_limit:
        raise HTTPException(
            status_code=409,
            detail="Лимит попыток исчерпан — обратитесь к руководителю",
        )

    questions = (
        (
            await db.execute(
                select(QuizQuestion)
                .where(QuizQuestion.quiz_id == quiz_id)
                .order_by(QuizQuestion.position)
            )
        )
        .scalars()
        .all()
    )
    if not questions:
        raise HTTPException(status_code=409, detail="В тесте нет вопросов")

    seed = secrets.randbelow(2**31)
    snapshot = build_snapshot(
        [
            {
                "id": q.id,
                "qtype": q.qtype,
                "prompt": q.prompt,
                "media_id": q.media_id,
                "options": q.options,
                "answer": q.answer,
                "points": q.points,
            }
            for q in questions
        ],
        shuffle_questions=quiz.shuffle_questions,
        shuffle_options=quiz.shuffle_options,
        seed=seed,
    )
    attempt = QuizAttempt(
        tenant_id=quiz.tenant_id,
        quiz_id=quiz_id,
        profile_id=profile.id,
        attempt_no=(attempts[-1].attempt_no + 1) if attempts else 1,
        seed=seed,
        snapshot=snapshot,
    )
    db.add(attempt)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Попытка уже создана — обновите страницу"
        ) from None
    await db.refresh(attempt)
    return _attempt_response(quiz, attempt)


@router.get("/learn/quiz-attempts/{attempt_id}", response_model=AttemptResponse)
async def get_attempt(
    attempt_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> AttemptResponse:
    attempt = await _get_attempt_or_404(db, attempt_id)
    quiz = await _get_quiz_or_404(db, attempt.quiz_id)
    profile = await get_profile(db, principal)
    if profile is None or attempt.profile_id != profile.id:
        role = await resolve_content_role(db, principal)
        if not lifecycle.can(role, "publisher"):
            raise HTTPException(status_code=404, detail="Попытка не найдена")
    return _attempt_response(quiz, attempt, with_results=True)


@router.patch("/learn/quiz-attempts/{attempt_id}", status_code=204)
async def save_answer(
    attempt_id: UUID,
    body: AnswerBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Автосохранение ответа per-question (обрыв связи не теряет прогресс)."""
    attempt = await _get_attempt_or_404(db, attempt_id)
    profile = await get_profile(db, principal)
    if profile is None or attempt.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Попытка не найдена")
    if attempt.finished_at is not None:
        raise HTTPException(status_code=409, detail="Попытка уже сдана")
    if body.question_id not in {q["id"] for q in attempt.snapshot}:
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    answers = dict(attempt.answers)
    answers[body.question_id] = body.value
    attempt.answers = answers
    await db.commit()


@router.post("/learn/quiz-attempts/{attempt_id}/submit", response_model=AttemptResponse)
async def submit_attempt(
    attempt_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> AttemptResponse:
    attempt = await _get_attempt_or_404(db, attempt_id)
    quiz = await _get_quiz_or_404(db, attempt.quiz_id)
    profile = await get_profile(db, principal)
    if profile is None or attempt.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Попытка не найдена")
    if attempt.finished_at is not None:
        return _attempt_response(quiz, attempt, with_results=True)

    scored = score_attempt(attempt.snapshot, attempt.answers)
    attempt.finished_at = datetime.now(UTC)

    if scored.open_question_ids:
        # Открытые вопросы → ручная проверка HR; финализация — в review.
        attempt.needs_review = True
        reviewers = (
            (
                await db.execute(
                    select(EmployeeProfile.id).where(
                        EmployeeProfile.content_role == "publisher",
                        EmployeeProfile.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        recipients = await _employee_ids(db, list(reviewers))
        await notify_many(
            db,
            tenant_id=quiz.tenant_id,
            employee_ids=list(recipients.values()),
            kind="quiz.review_needed",
            title="Нужна проверка открытых ответов",
            body=f"«{quiz.title}» — {profile.full_name} ждёт проверки теста.",
            url="/learn/admin/review",
            payload={"attempt_id": str(attempt.id)},
        )
    else:
        score_pct, passed = finalize(
            attempt.snapshot, scored.auto_points, None, quiz.pass_score_pct
        )
        attempt.score_pct = score_pct
        attempt.passed = passed
        if passed:
            await _award_quiz_events(db, quiz, profile.id, attempt)

    await db.commit()
    await db.refresh(attempt)
    return _attempt_response(quiz, attempt, with_results=True)


async def _award_quiz_events(
    db: AsyncSession, quiz: Quiz, profile_id: UUID, attempt: QuizAttempt
) -> None:
    await points.award(
        db,
        tenant_id=quiz.tenant_id,
        profile_id=profile_id,
        event_type="quiz.passed",
        object_type="quiz",
        object_id=quiz.id,
        weight_key="quiz.passed_retry" if attempt.attempt_no > 1 else None,
        meta={"attempt_no": attempt.attempt_no, "score_pct": attempt.score_pct},
    )
    if attempt.score_pct == 100:
        await points.award(
            db,
            tenant_id=quiz.tenant_id,
            profile_id=profile_id,
            event_type="quiz.perfect_bonus",
            object_type="quiz",
            object_id=quiz.id,
            meta={"attempt_no": attempt.attempt_no},
        )


# ─── Review (publisher) ──────────────────────────────────────────────────────


@router.get("/learn/review-queue", response_model=list[ReviewQueueItem])
async def review_queue(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[ReviewQueueItem]:
    await require_content_role(db, principal, "publisher")
    rows = await db.execute(
        select(QuizAttempt, Quiz, EmployeeProfile)
        .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
        .join(EmployeeProfile, EmployeeProfile.id == QuizAttempt.profile_id)
        .where(
            QuizAttempt.needs_review.is_(True),
            QuizAttempt.reviewed_at.is_(None),
            QuizAttempt.finished_at.is_not(None),
        )
        .order_by(QuizAttempt.finished_at)
    )
    out = []
    for attempt, quiz, profile in rows:
        open_count = sum(
            1
            for q in attempt.snapshot
            if q["qtype"] == "open"
            and isinstance(attempt.answers.get(q["id"]), str)
            and attempt.answers[q["id"]].strip()
        )
        out.append(
            ReviewQueueItem(
                attempt_id=attempt.id,
                quiz_id=quiz.id,
                quiz_title=quiz.title,
                course_id=quiz.course_id,
                profile_id=profile.id,
                employee_name=profile.full_name,
                finished_at=attempt.finished_at,
                open_question_count=open_count,
            )
        )
    return out


@router.post("/learn/quiz-attempts/{attempt_id}/review", response_model=AttemptResponse)
async def review_attempt(
    attempt_id: UUID,
    body: ReviewBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> AttemptResponse:
    await require_content_role(db, principal, "publisher")
    attempt = await _get_attempt_or_404(db, attempt_id)
    quiz = await _get_quiz_or_404(db, attempt.quiz_id)
    if attempt.finished_at is None or not attempt.needs_review:
        raise HTTPException(status_code=409, detail="Попытка не ждёт проверки")
    if attempt.reviewed_at is not None:
        raise HTTPException(status_code=409, detail="Попытка уже проверена")

    scored = score_attempt(attempt.snapshot, attempt.answers)
    score_pct, passed = finalize(
        attempt.snapshot, scored.auto_points, body.scores, quiz.pass_score_pct
    )
    attempt.review_scores = {k: float(v) for k, v in body.scores.items()}
    attempt.reviewed_by = principal.employee_id
    attempt.reviewed_at = datetime.now(UTC)
    attempt.score_pct = score_pct
    attempt.passed = passed
    if passed:
        await _award_quiz_events(db, quiz, attempt.profile_id, attempt)

    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="quiz_attempt",
        object_id=attempt.id,
        object_label=quiz.title,
        diff={"reviewed": {"old": None, "new": f"score={score_pct} passed={passed}"}},
    )

    recipients = await _employee_ids(db, [attempt.profile_id])
    await notify_many(
        db,
        tenant_id=quiz.tenant_id,
        employee_ids=list(recipients.values()),
        kind="quiz.reviewed",
        title=quiz.title,
        body=(
            f"Тест проверен: {score_pct}% — "
            + ("сдан. Поздравляем!" if passed else "не сдан. Можно попробовать ещё раз.")
        ),
        url=f"/learn/courses/{quiz.course_id}",
        payload={"quiz_id": str(quiz.id)},
    )
    await db.commit()
    await db.refresh(attempt)
    return _attempt_response(quiz, attempt, with_results=True)


# ─── Рейтинг ─────────────────────────────────────────────────────────────────


@router.get("/learn/rating", response_model=RatingResponse)
async def rating(
    period: str = Query(default="month", pattern="^(month|quarter)$"),
    scope: str = Query(default="all", pattern="^(all|store)$"),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> RatingResponse:
    profile = await get_profile(db, principal)
    since_expr = "date_trunc('month', now())" if period == "month" else (
        "date_trunc('quarter', now())"
    )

    store_filter = ""
    params: dict = {}
    if scope == "store":
        if profile is None or profile.store_id is None:
            return RatingResponse(
                period=period, scope=scope, rows=[], me=None, total_participants=0
            )
        store_filter = "AND p.store_id = :store_id"
        params["store_id"] = str(profile.store_id)

    rows = (
        await db.execute(
            # S608: f-string собирает ТОЛЬКО константы из белых списков выше
            # (since_expr, store_filter) — пользовательский ввод в параметрах.
            text(
                f"""
                SELECT p.id, p.full_name, pos.name AS position_name,
                       s.name AS store_name, SUM(e.points) AS pts
                FROM activity_events e
                JOIN employee_profiles p ON p.id = e.profile_id
                LEFT JOIN positions pos ON pos.id = p.position_id
                LEFT JOIN stores s ON s.id = p.store_id
                WHERE e.occurred_at >= {since_expr}
                  AND p.status = 'active'
                  {store_filter}
                GROUP BY p.id, p.full_name, pos.name, s.name
                ORDER BY pts DESC, p.full_name
                """  # noqa: S608 — f-string только из белых списков выше
            ),
            params,
        )
    ).all()

    my_id = profile.id if profile else None
    out_rows: list[RatingRow] = []
    me_row: RatingRow | None = None
    for rank, (pid, full_name, position_name, store_name, pts) in enumerate(rows, 1):
        row = RatingRow(
            profile_id=pid,
            full_name=full_name,
            position_name=position_name,
            store_name=store_name,
            points=float(pts or 0),
            rank=rank,
            is_me=pid == my_id,
        )
        if rank <= 50:
            out_rows.append(row)
        if pid == my_id:
            me_row = row
    return RatingResponse(
        period=period,
        scope=scope,
        rows=out_rows,
        me=me_row,
        total_participants=len(rows),
    )


# ─── Сертификаты ─────────────────────────────────────────────────────────────


@router.get("/learn/certificates")
async def my_certificates(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    profile = await get_profile(db, principal)
    if profile is None:
        return []
    rows = (
        (
            await db.execute(
                select(Certificate)
                .where(Certificate.profile_id == profile.id)
                .order_by(Certificate.issued_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(c.id),
            "serial": c.serial,
            "course_id": str(c.course_id),
            "course_title": c.course_title,
            "full_name": c.full_name,
            "issued_at": c.issued_at.isoformat(),
        }
        for c in rows
    ]


@router.get("/learn/certificates/{certificate_id}")
async def get_certificate(
    certificate_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cert = await db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Сертификат не найден")
    profile = await get_profile(db, principal)
    if profile is None or cert.profile_id != profile.id:
        role = await resolve_content_role(db, principal)
        if not lifecycle.can(role, "publisher"):
            raise HTTPException(status_code=404, detail="Сертификат не найден")
    return {
        "id": str(cert.id),
        "serial": cert.serial,
        "course_id": str(cert.course_id),
        "course_title": cert.course_title,
        "full_name": cert.full_name,
        "issued_at": cert.issued_at.isoformat(),
    }


