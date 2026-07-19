"""Аналитика обучения (Ф5, ТЗ §21).

Скоуп — через org_scope.resolve_scope: admin/publisher видят всю сеть,
ТУ — закреплённые магазины, франчайзи-владелец — свои магазины; линейному
персоналу аналитика недоступна. Опросы сюда НЕ входят — их агрегаты
отдаёт только survey_stats (анти-деанон инвариант Ф2).

«Темы провалов» — доля неверных ответов по вопросам тестов, считается по
снапшотам сданных попыток (то, что реально видел сотрудник).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.activity import ActivityEvent
from app.models.course import Course
from app.models.employee_profile import EmployeeProfile
from app.models.library import LibraryMaterial, MaterialAcknowledgement
from app.models.org import Position, Store
from app.models.progress import CourseAssignment, CourseProgress
from app.models.quiz import Quiz, QuizAttempt
from app.services import lifecycle
from app.services.content_access import resolve_content_role
from app.services.org_scope import resolve_scope
from app.services.quiz_scoring import score_attempt

router = APIRouter(tags=["learn-analytics"])

_EXPORT_ROW_LIMIT = 5000
_FAIL_ATTEMPT_LIMIT = 2000


class OverviewStats(BaseModel):
    employees_total: int
    employees_linked: int
    engaged_30d: int
    points_30d: float


class CourseStat(BaseModel):
    id: UUID
    title: str
    course_type: str
    enrolled: int
    completed: int
    avg_quiz_score: int | None


class FailQuestion(BaseModel):
    prompt: str
    quiz_title: str
    attempts: int
    fail_rate_pct: int


class AckStat(BaseModel):
    id: UUID
    title: str
    acked: int
    total: int


class AnalyticsResponse(BaseModel):
    scope: str
    overview: OverviewStats
    courses: list[CourseStat]
    fail_questions: list[FailQuestion]
    acks: list[AckStat]


async def _scope_profile_ids(
    db: AsyncSession, principal: Principal
) -> tuple[str, list[UUID] | None]:
    """→ (scope_kind, profile_ids | None=вся сеть). 403 для линейных."""
    role = await resolve_content_role(db, principal)
    scope = await resolve_scope(db, principal)
    if lifecycle.can(role, "publisher") or scope.kind == "all":
        return "all", None
    if scope.kind == "stores":
        rows = await db.execute(
            select(EmployeeProfile.id).where(
                EmployeeProfile.store_id.in_(scope.store_ids or frozenset()),
                EmployeeProfile.status == "active",
            )
        )
        return "stores", [r[0] for r in rows]
    raise HTTPException(
        status_code=403,
        detail="Аналитика доступна руководителям и публикаторам",
    )


def _profiles_filter(profile_ids: list[UUID] | None):
    if profile_ids is None:
        return EmployeeProfile.status == "active"
    return EmployeeProfile.id.in_(profile_ids or [UUID(int=0)])


@router.get("/learn/analytics", response_model=AnalyticsResponse)
async def analytics(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsResponse:
    scope_kind, profile_ids = await _scope_profile_ids(db, principal)
    since_30d = datetime.now(UTC) - timedelta(days=30)

    profiles = (
        (await db.execute(select(EmployeeProfile).where(_profiles_filter(profile_ids))))
        .scalars()
        .all()
    )
    id_set = {p.id for p in profiles}

    engaged_rows = await db.execute(
        select(ActivityEvent.profile_id, func.sum(ActivityEvent.points))
        .where(ActivityEvent.occurred_at >= since_30d)
        .group_by(ActivityEvent.profile_id)
    )
    engaged = 0
    points_30d = 0.0
    for pid, pts in engaged_rows:
        if pid in id_set:
            engaged += 1
            points_30d += float(pts or 0)

    overview = OverviewStats(
        employees_total=len(profiles),
        employees_linked=sum(1 for p in profiles if p.employee_id is not None),
        engaged_30d=engaged,
        points_30d=round(points_30d, 1),
    )

    # Курсы: старт/завершение в скоупе + средний балл сданных тестов.
    courses = (
        (
            await db.execute(
                select(Course).where(Course.status == "published").order_by(Course.title)
            )
        )
        .scalars()
        .all()
    )
    progress_rows = (
        await db.execute(
            select(
                CourseProgress.course_id,
                CourseProgress.profile_id,
                CourseProgress.completed_at,
            )
        )
    ).all()
    quiz_rows = (
        await db.execute(
            select(Quiz.course_id, QuizAttempt.profile_id, QuizAttempt.score_pct)
            .join(QuizAttempt, QuizAttempt.quiz_id == Quiz.id)
            .where(QuizAttempt.passed.is_(True))
        )
    ).all()

    course_stats = []
    for course in courses:
        in_scope = [
            (pid, completed)
            for cid, pid, completed in progress_rows
            if cid == course.id and pid in id_set
        ]
        scores = [
            s for cid, pid, s in quiz_rows if cid == course.id and pid in id_set and s is not None
        ]
        course_stats.append(
            CourseStat(
                id=course.id,
                title=course.title,
                course_type=course.course_type,
                enrolled=len(in_scope),
                completed=sum(1 for _, c in in_scope if c is not None),
                avg_quiz_score=round(sum(scores) / len(scores)) if scores else None,
            )
        )

    # Темы провалов: доля неверных по вопросам сданных попыток.
    attempts = (
        (
            await db.execute(
                select(QuizAttempt, Quiz.title)
                .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                .where(QuizAttempt.finished_at.is_not(None))
                .order_by(QuizAttempt.finished_at.desc())
                .limit(_FAIL_ATTEMPT_LIMIT)
            )
        )
        .all()
    )
    agg: dict[tuple[str, str], list[int]] = {}  # (prompt, quiz) -> [fails, total]
    for attempt, quiz_title in attempts:
        if attempt.profile_id not in id_set:
            continue
        result = score_attempt(attempt.snapshot, attempt.answers)
        prompts = {q["id"]: q["prompt"] for q in attempt.snapshot}
        for qid, verdict in result.per_question.items():
            key = (prompts.get(qid, "?"), quiz_title)
            bucket = agg.setdefault(key, [0, 0])
            bucket[1] += 1
            if verdict is False:
                bucket[0] += 1
    fail_questions = sorted(
        (
            FailQuestion(
                prompt=prompt,
                quiz_title=quiz_title,
                attempts=total,
                fail_rate_pct=round(fails / total * 100),
            )
            for (prompt, quiz_title), (fails, total) in agg.items()
            if total >= 2 and fails > 0
        ),
        key=lambda f: (-f.fail_rate_pct, -f.attempts),
    )[:10]

    # Ознакомления: подписано/в скоупе по обязательным материалам.
    materials = (
        (
            await db.execute(
                select(LibraryMaterial).where(
                    LibraryMaterial.status == "published",
                    LibraryMaterial.requires_acknowledgement.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    ack_rows = (
        await db.execute(
            select(
                MaterialAcknowledgement.material_id,
                MaterialAcknowledgement.profile_id,
            ).distinct()
        )
    ).all()
    acks = [
        AckStat(
            id=m.id,
            title=m.title,
            acked=sum(1 for mid, pid in ack_rows if mid == m.id and pid in id_set),
            total=len(id_set),
        )
        for m in materials
    ]

    return AnalyticsResponse(
        scope=scope_kind,
        overview=overview,
        courses=course_stats,
        fail_questions=fail_questions,
        acks=acks,
    )


@router.get("/learn/analytics/export")
async def export_csv(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """CSV-отчёт по обучению сотрудников в скоупе (лимит 5000 строк)."""
    _scope_kind, profile_ids = await _scope_profile_ids(db, principal)

    profiles = (
        (
            await db.execute(
                select(EmployeeProfile, Position.name, Store.name)
                .outerjoin(Position, Position.id == EmployeeProfile.position_id)
                .outerjoin(Store, Store.id == EmployeeProfile.store_id)
                .where(_profiles_filter(profile_ids))
                .order_by(EmployeeProfile.full_name)
                .limit(_EXPORT_ROW_LIMIT)
            )
        )
        .all()
    )
    id_list = [p.id for p, _, _ in profiles]

    progress = (
        await db.execute(
            select(
                CourseProgress.profile_id,
                func.count(),
                func.count(CourseProgress.completed_at),
            )
            .where(CourseProgress.profile_id.in_(id_list or [UUID(int=0)]))
            .group_by(CourseProgress.profile_id)
        )
    ).all()
    progress_map = {pid: (started, done) for pid, started, done in progress}

    assigned = (
        await db.execute(
            select(CourseAssignment.profile_id, func.count())
            .where(CourseAssignment.profile_id.in_(id_list or [UUID(int=0)]))
            .group_by(CourseAssignment.profile_id)
        )
    ).all()
    assigned_map = dict(assigned)

    quizzes_passed = (
        await db.execute(
            select(QuizAttempt.profile_id, func.count(func.distinct(QuizAttempt.quiz_id)))
            .where(
                QuizAttempt.profile_id.in_(id_list or [UUID(int=0)]),
                QuizAttempt.passed.is_(True),
            )
            .group_by(QuizAttempt.profile_id)
        )
    ).all()
    quiz_map = dict(quizzes_passed)

    points = (
        await db.execute(
            select(ActivityEvent.profile_id, func.sum(ActivityEvent.points))
            .where(ActivityEvent.profile_id.in_(id_list or [UUID(int=0)]))
            .group_by(ActivityEvent.profile_id)
        )
    ).all()
    points_map = {pid: float(pts or 0) for pid, pts in points}

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "ФИО",
            "Email",
            "Должность",
            "Магазин",
            "Курсов назначено",
            "Курсов начато",
            "Курсов завершено",
            "Тестов сдано",
            "Баллы рейтинга",
            "Последняя активность",
        ]
    )
    for profile, position_name, store_name in profiles:
        started, done = progress_map.get(profile.id, (0, 0))
        writer.writerow(
            [
                profile.full_name,
                profile.email,
                position_name or "",
                store_name or "",
                assigned_map.get(profile.id, 0),
                started,
                done,
                quiz_map.get(profile.id, 0),
                points_map.get(profile.id, 0),
                profile.last_activity_at.strftime("%Y-%m-%d")
                if profile.last_activity_at
                else "",
            ]
        )

    # BOM — чтобы Excel открыл кириллицу без танцев с кодировкой.
    payload = ("﻿" + buffer.getvalue()).encode("utf-8")
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="learning-report.csv"'
        },
    )
