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
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from signaris_auth import Principal
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_auth
from app.models.activity import ActivityEvent
from app.models.course import Course
from app.models.employee_profile import EmployeeProfile
from app.models.library import LibraryMaterial, MaterialAcknowledgement
from app.models.progress import CourseProgress
from app.models.quiz import Quiz, QuizAttempt
from app.services import lifecycle
from app.services.audience_resolver import learning_population_filter
from app.services.content_access import resolve_content_role
from app.services.learning_progress import (
    ROWS_HARD_CAP,
    LearningRow,
    collect_learning_rows,
    collect_person_detail,
    profiles_filter,
    summarize,
)
from app.services.org_scope import resolve_scope
from app.services.quiz_scoring import score_attempt
from app.services.timefmt import fmt_dt

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


class EmployeeProgressRow(BaseModel):
    """Строка «Прогресса сотрудников». Та же схема — шапка панели по человеку."""

    profile_id: UUID
    full_name: str
    email: str
    position_id: UUID | None
    position_name: str | None
    store_id: UUID | None
    store_name: str | None
    has_account: bool
    auth_state: str
    mandatory_total: int
    mandatory_done: int
    mandatory_pct: int | None
    courses_available: int
    courses_started: int
    courses_completed: int
    quizzes_passed: int
    certificates: int
    points: float
    last_activity_at: datetime | None

    @classmethod
    def of(cls, row: LearningRow) -> EmployeeProgressRow:
        return cls(
            profile_id=row.profile_id,
            full_name=row.full_name,
            email=row.email,
            position_id=row.position_id,
            position_name=row.position_name,
            store_id=row.store_id,
            store_name=row.store_name,
            has_account=row.has_account,
            auth_state=row.auth_state,
            mandatory_total=row.mandatory_total,
            mandatory_done=row.mandatory_done,
            mandatory_pct=row.mandatory_pct,
            courses_available=row.courses_available,
            courses_started=row.courses_started,
            courses_completed=row.courses_completed,
            quizzes_passed=row.quizzes_passed,
            certificates=row.certificates,
            points=row.points,
            last_activity_at=row.last_activity_at,
        )


class EmployeeProgressSummary(BaseModel):
    people: int
    without_account: int
    never_active: int
    completed_all: int
    completed_none: int
    mandatory_total: int
    mandatory_done: int
    mandatory_pct: int | None


class EmployeeProgressList(BaseModel):
    scope: str
    total: int
    #: Упёрлись в потолок. Поле есть с первого дня: без него экран при росте
    #: тенанта начал бы врать молча — ровно та беда, из-за которой появился
    #: `employeeListCaption` (ОС 31.08, «в Сотрудниках видно не всех»).
    truncated: bool
    summary: EmployeeProgressSummary
    items: list[EmployeeProgressRow]


class PersonCourseRow(BaseModel):
    course_id: UUID
    title: str
    course_type: str
    course_status: str
    required: bool
    source: str
    status: str
    lessons_total: int
    lessons_completed: int
    started_at: datetime | None
    completed_at: datetime | None
    due_at: datetime | None
    certificate_serial: str | None


class PersonAttemptRow(BaseModel):
    attempt_id: UUID
    quiz_title: str
    attempt_no: int
    finished_at: datetime | None
    score_pct: int | None
    state: str


class EmployeeProgressDetail(BaseModel):
    profile: EmployeeProgressRow
    courses: list[PersonCourseRow]
    attempts: list[PersonAttemptRow]


async def _scope_profile_ids(
    db: AsyncSession, principal: Principal
) -> tuple[str, list[UUID] | None]:
    """→ (scope_kind, profile_ids | None=вся сеть). 403 для линейных.

    Собственный профиль руководителя ВХОДИТ в скоуп (16.09). Три других гейта —
    `list_employees`, `library.ack_report` и `get_employee` — уже включают его,
    и расхождение стоило бы дорого: ТУ получал бы 404 на разбор собственного
    обучения, хотя его же карточка по `/learn/employees/{id}` отдаётся. Цена
    правки видна в цифрах: у руководителя со своим профилем вне закреплённых
    магазинов `employees_total` вырастет на единицу.
    """
    role = await resolve_content_role(db, principal)
    scope = await resolve_scope(db, principal)
    if lifecycle.can(role, "publisher") or scope.kind == "all":
        return "all", None
    if scope.kind == "stores":
        rows = await db.execute(
            select(EmployeeProfile.id).where(
                or_(
                    EmployeeProfile.store_id.in_(scope.store_ids or frozenset()),
                    EmployeeProfile.id == (scope.profile_id or UUID(int=0)),
                ),
                learning_population_filter(),
            )
        )
        return "stores", [r[0] for r in rows]
    raise HTTPException(
        status_code=403,
        detail="Аналитика доступна руководителям и публикаторам",
    )


def _profiles_filter(profile_ids: list[UUID] | None):
    """Тонкая обёртка над общим правилом — чтобы определение было одно."""
    return profiles_filter(profile_ids)


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


# ─── Прогресс обучения по сотрудникам ────────────────────────────────────────


@router.get("/learn/analytics/employees", response_model=EmployeeProgressList)
async def employee_progress(
    # Annotated, а НЕ `= Query(...)`: в этом проекте тесты зовут функции ручек
    # напрямую, и значением по умолчанию тогда становится объект `Query`, а не
    # None — поиск падал бы в TypeError. Валидация длины при этом сохраняется.
    q: Annotated[str | None, Query(max_length=255)] = None,
    store_id: UUID | None = None,
    position_id: UUID | None = None,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> EmployeeProgressList:
    """Прогресс по людям: «обязательных пройдено X из N» плюс общие счётчики.

    Выдача НЕ обрезается (решение владельца 16.09 после живого бага: потолок в
    50 строк однажды спрятал 84% справочника). `total` и `truncated` всё равно
    в ответе — чтобы при росте тенанта экран сказал правду, а не подрезал
    список молча.
    """
    scope_kind, profile_ids = await _scope_profile_ids(db, principal)
    rows = await collect_learning_rows(
        db, profile_ids, q=q, store_id=store_id, position_id=position_id
    )
    summary = summarize(rows)
    return EmployeeProgressList(
        scope=scope_kind,
        total=len(rows),
        truncated=len(rows) >= ROWS_HARD_CAP,
        summary=EmployeeProgressSummary(
            people=summary.people,
            without_account=summary.without_account,
            never_active=summary.never_active,
            completed_all=summary.completed_all,
            completed_none=summary.completed_none,
            mandatory_total=summary.mandatory_total,
            mandatory_done=summary.mandatory_done,
            mandatory_pct=summary.mandatory_pct,
        ),
        items=[EmployeeProgressRow.of(r) for r in rows],
    )


@router.get(
    "/learn/analytics/employees/{profile_id}", response_model=EmployeeProgressDetail
)
async def employee_progress_detail(
    profile_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> EmployeeProgressDetail:
    """Разбор по человеку: какие курсы пройдены, какие нет.

    Вне скоупа — 404, а не 403: 403 подтвердил бы, что карточка существует, и
    по коду ответа можно было бы перебирать состав чужих магазинов. Тот же
    выбор уже сделан в `employees.get_employee`.
    """
    _scope_kind, profile_ids = await _scope_profile_ids(db, principal)
    profile = await db.get(EmployeeProfile, profile_id)
    if profile is None or (profile_ids is not None and profile.id not in profile_ids):
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    detail = await collect_person_detail(db, profile)
    return EmployeeProgressDetail(
        profile=EmployeeProgressRow.of(detail.row),
        courses=[
            PersonCourseRow(
                course_id=c.course_id,
                title=c.title,
                course_type=c.course_type,
                course_status=c.course_status,
                required=c.required,
                source=c.source,
                status=c.status,
                lessons_total=c.lessons_total,
                lessons_completed=c.lessons_completed,
                started_at=c.started_at,
                completed_at=c.completed_at,
                due_at=c.due_at,
                certificate_serial=c.certificate_serial,
            )
            for c in detail.courses
        ],
        attempts=[
            PersonAttemptRow(
                attempt_id=a.attempt_id,
                quiz_title=a.quiz_title,
                attempt_no=a.attempt_no,
                finished_at=a.finished_at,
                score_pct=a.score_pct,
                state=a.state,
            )
            for a in detail.attempts
        ],
    )


_AUTH_STATE_LABEL = {
    "no_account": "нет учётки",
    "not_linked": "не привязана",
    "not_logged_in": "не заходил(а)",
    "blocked": "заблокирована",
    "deleted": "удалена",
    "active": "активна",
}


@router.get("/learn/analytics/export")
async def export_csv(
    # Annotated, а НЕ `= Query(...)`: в этом проекте тесты зовут функции ручек
    # напрямую, и значением по умолчанию тогда становится объект `Query`, а не
    # None — поиск падал бы в TypeError. Валидация длины при этом сохраняется.
    q: Annotated[str | None, Query(max_length=255)] = None,
    store_id: UUID | None = None,
    position_id: UUID | None = None,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """CSV по обучению сотрудников в скоупе — ТЕМИ ЖЕ числами, что на экране.

    Считает общий `collect_learning_rows`, поэтому выгрузка и «Прогресс
    сотрудников» не могут разойтись. Принимает те же фильтры — «выгрузи то,
    что вижу».

    Колонка «Курсов назначено» из прежней версии УБРАНА, а не дозаполнена: она
    считала строки `course_assignments` (на проде одна на весь тенант) и почти
    у всех была нулём. Переименование, а не тихая смена смысла, — чтобы
    сохранённый ранее файл нельзя было спутать с новым.
    """
    scope_kind, profile_ids = await _scope_profile_ids(db, principal)
    rows = await collect_learning_rows(
        db, profile_ids, q=q, store_id=store_id, position_id=position_id
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "ФИО",
            "Email",
            "Должность",
            "Магазин",
            "Учётка",
            "Обязательных всего",
            "Обязательных пройдено",
            "Обязательных %",
            "Курсов доступно",
            "Курсов начато",
            "Курсов завершено",
            "Тестов сдано",
            "Сертификатов",
            "Баллы рейтинга",
            "Последняя активность",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.full_name,
                row.email,
                row.position_name or "",
                row.store_name or "",
                _AUTH_STATE_LABEL.get(row.auth_state, row.auth_state),
                row.mandatory_total,
                row.mandatory_done,
                "" if row.mandatory_pct is None else row.mandatory_pct,
                row.courses_available,
                row.courses_started,
                row.courses_completed,
                row.quizzes_passed,
                row.certificates,
                row.points,
                fmt_dt(row.last_activity_at, "%Y-%m-%d") if row.last_activity_at else "",
            ]
        )

    # BOM — чтобы Excel открыл кириллицу без танцев с кодировкой.
    payload = ("﻿" + buffer.getvalue()).encode("utf-8")
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="learning-report-{stamp}.csv"'
            )
        },
    )
