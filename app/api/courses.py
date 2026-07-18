"""Курсы и уроки API (Ф3a, ТЗ §4-5).

Инварианты (adversarial-ревью плана):
- видимость курса потребителю = published AND (audience-член OR активное
  назначение) — назначенный вне аудитории курс ОБЯЗАН быть виден;
- sequential-замки проверяются НА СЕРВЕРЕ (GET урока → 403), с
  монотонностью: урок с существующим прогрессом не запирается;
- «Завершить урок» — явное действие с предусловиями: gate-вопросы отвечены,
  обязательные видео досмотрены (покрытие интервалов ≥90%);
- видео-интервалы мёржатся под SELECT FOR UPDATE (два устройства);
- completed_at курса иммутабелен (добавление уроков не отбирает завершение).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from signaris_auth import Principal
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import enforce_rate_limit, get_db, require_auth
from app.models.audience import AudienceMember
from app.models.course import Course, CourseLesson, LessonTemplate, MediaFile
from app.models.employee_profile import EmployeeProfile
from app.models.progress import CourseAssignment, CourseProgress, LessonProgress
from app.schemas.course import (
    AssignBody,
    BlockAnswerBody,
    CourseCreate,
    CourseDetailResponse,
    CourseListResponse,
    CourseResponse,
    CourseUpdate,
    LessonContentResponse,
    LessonCreate,
    LessonMeta,
    LessonUpdate,
    ReorderBody,
    TemplateCreate,
    TemplateResponse,
    VideoProgressBody,
)
from app.schemas.library import AudienceBody, StatusBody
from app.services import audit, lifecycle
from app.services.audience_resolver import RuleSpec, set_object_audience, visible_filter
from app.services.certificate import issue_if_earned
from app.services.content_access import require_content_role, resolve_content_role
from app.services.learn_media import sign_media_path
from app.services.learn_notify import _employee_ids
from app.services.lesson_content import (
    RichContentError,
    check_answer,
    collect_gate_blocks,
    collect_required_videos,
    prepare_for_consumer,
    validate_lesson_content,
)
from app.services.notify_batch import notify_many
from app.services.org_scope import get_profile
from app.services.points import award
from app.services.quiz_gate import passed_required_quiz_lessons
from app.services.search_indexer import delete_document, upsert_document
from app.services.video_progress import is_watched, merge_intervals

router = APIRouter(tags=["learn-courses"])

_OBJECT_TYPE = "course"


def _rule_specs(body: AudienceBody) -> list[RuleSpec]:
    return [
        RuleSpec(
            mode=r.mode,
            profile_ids=frozenset(r.profile_ids),
            position_ids=frozenset(r.position_ids),
            position_group_ids=frozenset(r.position_group_ids),
            store_ids=frozenset(r.store_ids),
            store_group_ids=frozenset(r.store_group_ids),
            franchisee_ids=frozenset(r.franchisee_ids),
            franchisee_group_ids=frozenset(r.franchisee_group_ids),
            department_ids=frozenset(r.department_ids),
            user_group_ids=frozenset(r.user_group_ids),
        )
        for r in body.rules
    ]


async def _get_course_or_404(db: AsyncSession, course_id: UUID) -> Course:
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Курс не найден")
    return course


async def _get_lesson_or_404(db: AsyncSession, lesson_id: UUID) -> CourseLesson:
    lesson = await db.get(CourseLesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Урок не найден")
    return lesson


def _require_manage(course: Course, principal: Principal, role: lifecycle.ContentRole) -> None:
    if lifecycle.can(role, "publisher"):
        return
    if role == "author" and course.created_by == principal.employee_id:
        return
    raise HTTPException(status_code=403, detail="Это не ваш курс")


async def _course_visible_to(
    db: AsyncSession,
    course: Course,
    principal: Principal,
    role: lifecycle.ContentRole,
    profile_id: UUID | None,
) -> bool:
    if lifecycle.can(role, "publisher"):
        return True
    if role == "author" and course.created_by == principal.employee_id:
        return True
    if course.status != "published":
        return False
    if profile_id is not None:
        # Назначение = имплицитная видимость (ревью §8).
        assigned = (
            await db.execute(
                select(CourseAssignment.profile_id).where(
                    CourseAssignment.course_id == course.id,
                    CourseAssignment.profile_id == profile_id,
                )
            )
        ).scalar_one_or_none()
        if assigned is not None:
            return True
    if course.audience_id is None:
        return True
    if profile_id is None:
        return False
    member = await db.execute(
        select(AudienceMember.profile_id).where(
            AudienceMember.audience_id == course.audience_id,
            AudienceMember.profile_id == profile_id,
        )
    )
    return member.scalar_one_or_none() is not None


async def _published_lessons(db: AsyncSession, course_id: UUID) -> list[CourseLesson]:
    return list(
        (
            await db.execute(
                select(CourseLesson)
                .where(
                    CourseLesson.course_id == course_id,
                    CourseLesson.status == "published",
                )
                .order_by(CourseLesson.position, CourseLesson.created_at)
            )
        )
        .scalars()
        .all()
    )


async def _progress_map(
    db: AsyncSession, course_id: UUID, profile_id: UUID
) -> dict[UUID, LessonProgress]:
    rows = (
        (
            await db.execute(
                select(LessonProgress).where(
                    LessonProgress.course_id == course_id,
                    LessonProgress.profile_id == profile_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return {p.lesson_id: p for p in rows}


def _lesson_locked(
    course: Course,
    lessons: list[CourseLesson],
    lesson: CourseLesson,
    progress: dict[UUID, LessonProgress],
    quiz_gate: dict[UUID, bool] | None = None,
) -> bool:
    """Серверный замок. Монотонность: свой прогресс = никогда не заперт.

    quiz_gate (Ф3b): lesson_id → пройден ли его required-тест; урок с
    unlock_rule='after_prev_test' дополнительно требует сданный тест
    предыдущего урока."""
    if lesson.id in progress:
        return False
    if course.progression_mode == "free":
        return False
    if course.progression_mode == "mixed" and lesson.unlock_rule == "free":
        return False
    prev_lesson: CourseLesson | None = None
    for prev in lessons:
        if prev.id == lesson.id:
            break
        prev_lesson = prev
        prev_progress = progress.get(prev.id)
        if prev_progress is None or prev_progress.status != "completed":
            return True
    return (
        lesson.unlock_rule == "after_prev_test"
        and prev_lesson is not None
        and quiz_gate is not None
        and quiz_gate.get(prev_lesson.id) is False
    )


async def _reindex(db: AsyncSession, course: Course) -> None:
    if course.status == "published":
        await upsert_document(
            db,
            tenant_id=course.tenant_id,
            object_type=_OBJECT_TYPE,
            object_id=course.id,
            title=course.title,
            snippet=course.description,
            audience_id=course.audience_id,
            published_at=course.published_at,
            url_path=f"/learn/courses/{course.id}",
        )
    else:
        await delete_document(db, object_type=_OBJECT_TYPE, object_id=course.id)


async def _update_course_progress(
    db: AsyncSession, course: Course, profile_id: UUID
) -> None:
    lessons = await _published_lessons(db, course.id)
    total = len(lessons)
    completed = 0
    if lessons:
        completed = (
            await db.execute(
                select(func.count())
                .select_from(LessonProgress)
                .where(
                    LessonProgress.course_id == course.id,
                    LessonProgress.profile_id == profile_id,
                    LessonProgress.status == "completed",
                    LessonProgress.lesson_id.in_([lesson.id for lesson in lessons]),
                )
            )
        ).scalar_one()
    now = datetime.now(UTC)
    stmt = pg_insert(CourseProgress).values(
        profile_id=profile_id,
        course_id=course.id,
        tenant_id=course.tenant_id,
        lessons_completed=completed,
        lessons_total=total,
        completed_at=now if total > 0 and completed >= total else None,
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["profile_id", "course_id"],
            set_={
                "lessons_completed": completed,
                "lessons_total": total,
                # Иммутабельность завершения: только выставляем, не сбрасываем.
                "completed_at": func.coalesce(
                    CourseProgress.completed_at,
                    now if total > 0 and completed >= total else None,
                ),
            },
        )
    )


# --- Каталог -----------------------------------------------------------------


@router.get("/learn/courses", response_model=CourseListResponse)
async def list_courses(
    manage: bool = Query(default=False),
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CourseListResponse:
    role = await resolve_content_role(db, principal)
    profile = await get_profile(db, principal)
    profile_id = profile.id if profile else None

    if manage and lifecycle.can(role, "publisher"):
        stmt = select(Course)
    elif manage and role == "author":
        stmt = select(Course).where(
            (Course.created_by == principal.employee_id)
            | (
                (Course.status == "published")
                & visible_filter(Course, profile_id or UUID(int=0))
            )
        )
    else:
        stmt = select(Course).where(
            Course.status == "published",
            visible_filter(Course, profile_id or UUID(int=0)),
        )
    courses = list(
        (await db.execute(stmt.order_by(Course.position, Course.created_at))).scalars().all()
    )

    # Назначенные, но не видимые по audience — доклеиваем (ревью §8).
    if profile_id and not manage:
        visible_ids = {c.id for c in courses}
        assigned_rows = (
            (
                await db.execute(
                    select(Course)
                    .join(CourseAssignment, CourseAssignment.course_id == Course.id)
                    .where(
                        CourseAssignment.profile_id == profile_id,
                        Course.status == "published",
                    )
                )
            )
            .scalars()
            .all()
        )
        for c in assigned_rows:
            if c.id not in visible_ids:
                courses.append(c)

    course_ids = [c.id for c in courses]
    progress: dict[UUID, CourseProgress] = {}
    assignments: dict[UUID, CourseAssignment] = {}
    lesson_totals: dict[UUID, int] = {}
    if course_ids:
        if profile_id:
            for p in (
                (
                    await db.execute(
                        select(CourseProgress).where(
                            CourseProgress.profile_id == profile_id,
                            CourseProgress.course_id.in_(course_ids),
                        )
                    )
                )
                .scalars()
                .all()
            ):
                progress[p.course_id] = p
            for a in (
                (
                    await db.execute(
                        select(CourseAssignment).where(
                            CourseAssignment.profile_id == profile_id,
                            CourseAssignment.course_id.in_(course_ids),
                        )
                    )
                )
                .scalars()
                .all()
            ):
                assignments[a.course_id] = a
        for course_id, count in await db.execute(
            select(CourseLesson.course_id, func.count())
            .where(
                CourseLesson.course_id.in_(course_ids),
                CourseLesson.status == "published",
            )
            .group_by(CourseLesson.course_id)
        ):
            lesson_totals[course_id] = count

    items = []
    for c in courses:
        resp = CourseResponse.model_validate(c)
        p = progress.get(c.id)
        a = assignments.get(c.id)
        resp.lessons_total = lesson_totals.get(c.id, 0)
        resp.lessons_completed = p.lessons_completed if p else 0
        resp.completed = bool(p and p.completed_at)
        resp.enrolled = bool(a or p or c.course_type == "mandatory")
        resp.due_at = a.due_at if a else None
        items.append(resp)
    return CourseListResponse(items=items, content_role=role)


@router.get("/learn/courses/{course_id}", response_model=CourseDetailResponse)
async def get_course(
    course_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CourseDetailResponse:
    role = await resolve_content_role(db, principal)
    course = await _get_course_or_404(db, course_id)
    profile = await get_profile(db, principal)
    profile_id = profile.id if profile else None
    if not await _course_visible_to(db, course, principal, role, profile_id):
        raise HTTPException(status_code=404, detail="Курс не найден")

    manager = lifecycle.can(role, "publisher") or (
        role == "author" and course.created_by == principal.employee_id
    )
    if manager:
        lessons = list(
            (
                await db.execute(
                    select(CourseLesson)
                    .where(CourseLesson.course_id == course_id)
                    .order_by(CourseLesson.position, CourseLesson.created_at)
                )
            )
            .scalars()
            .all()
        )
    else:
        lessons = await _published_lessons(db, course_id)

    progress = await _progress_map(db, course_id, profile_id) if profile_id else {}
    published = [lesson for lesson in lessons if lesson.status == "published"]
    quiz_gate = (
        await passed_required_quiz_lessons(db, course_id, profile_id)
        if profile_id and not manager
        else {}
    )

    metas = []
    for lesson in lessons:
        locked = (
            _lesson_locked(course, published, lesson, progress, quiz_gate)
            if lesson.status == "published" and not manager
            else False
        )
        p = progress.get(lesson.id)
        metas.append(
            LessonMeta(
                id=lesson.id,
                title=lesson.title,
                position=lesson.position,
                content_format=lesson.content_format,
                unlock_rule=lesson.unlock_rule,
                status=lesson.status,
                locked=locked,
                completed=bool(p and p.status == "completed"),
                started=p is not None,
            )
        )

    resp = CourseDetailResponse.model_validate(course)
    resp.lessons = metas
    resp.lessons_total = len(published)
    resp.lessons_completed = sum(1 for m in metas if m.completed and m.status == "published")
    if profile_id:
        a = (
            await db.execute(
                select(CourseAssignment).where(
                    CourseAssignment.course_id == course_id,
                    CourseAssignment.profile_id == profile_id,
                )
            )
        ).scalar_one_or_none()
        resp.enrolled = bool(a or progress or course.course_type == "mandatory")
        resp.due_at = a.due_at if a else None
        cp = (
            await db.execute(
                select(CourseProgress).where(
                    CourseProgress.course_id == course_id,
                    CourseProgress.profile_id == profile_id,
                )
            )
        ).scalar_one_or_none()
        resp.completed = bool(cp and cp.completed_at)
    return resp


# --- CRUD курса --------------------------------------------------------------


@router.post("/learn/courses", response_model=CourseResponse, status_code=201)
async def create_course(
    body: CourseCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CourseResponse:
    await require_content_role(db, principal, "author")
    course = Course(
        tenant_id=principal.tenant_id,
        title=body.title,
        description=body.description,
        course_type=body.course_type,
        progression_mode=body.progression_mode,
        owner_id=principal.employee_id,
        created_by=principal.employee_id,
    )
    db.add(course)
    await db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type=_OBJECT_TYPE,
        object_id=course.id,
        object_label=course.title,
    )
    await db.commit()
    await db.refresh(course)
    return CourseResponse.model_validate(course)


@router.patch("/learn/courses/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: UUID,
    body: CourseUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CourseResponse:
    role = await require_content_role(db, principal, "author")
    course = await _get_course_or_404(db, course_id)
    _require_manage(course, principal, role)
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(course, name, value)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type=_OBJECT_TYPE,
        object_id=course.id,
        object_label=course.title,
    )
    await _reindex(db, course)
    await db.commit()
    await db.refresh(course)
    return CourseResponse.model_validate(course)


@router.delete("/learn/courses/{course_id}", status_code=204)
async def delete_course(
    course_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await require_content_role(db, principal, "author")
    course = await _get_course_or_404(db, course_id)
    _require_manage(course, principal, role)
    if course.published_at is not None:
        raise HTTPException(status_code=409, detail="Курс публиковался — используйте архив")
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type=_OBJECT_TYPE,
        object_id=course.id,
        object_label=course.title,
    )
    await delete_document(db, object_type=_OBJECT_TYPE, object_id=course.id)
    await db.delete(course)
    await db.commit()


@router.post("/learn/courses/{course_id}/status", response_model=CourseResponse)
async def change_course_status(
    course_id: UUID,
    body: StatusBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CourseResponse:
    role = await require_content_role(db, principal, "author")
    course = await _get_course_or_404(db, course_id)
    _require_manage(course, principal, role)
    if body.status == "published" and not await _published_lessons(db, course_id):
        raise HTTPException(
            status_code=422, detail="Опубликуйте хотя бы один урок внутри курса"
        )

    was_published = course.status == "published"
    lifecycle.transition(
        db,
        course,
        body.status,
        actor_id=principal.employee_id,
        role=role,
        tenant_id=principal.tenant_id,
        object_type=_OBJECT_TYPE,
        object_label=course.title,
    )
    await _reindex(db, course)

    if course.status == "published" and not was_published:
        # Уведомляем аудиторию (mandatory — особенно) о новом курсе.
        if course.audience_id is None:
            rows = await db.execute(
                select(EmployeeProfile.id).where(EmployeeProfile.status == "active")
            )
        else:
            rows = await db.execute(
                select(AudienceMember.profile_id).where(
                    AudienceMember.audience_id == course.audience_id
                )
            )
        recipients = await _employee_ids(db, [r[0] for r in rows])
        await notify_many(
            db,
            tenant_id=course.tenant_id,
            employee_ids=list(recipients.values()),
            kind="course.assigned",
            title=course.title,
            body=(
                "Вам назначен обязательный курс."
                if course.course_type == "mandatory"
                else "Доступен новый курс — начните обучение."
            ),
            url=f"/learn/courses/{course.id}",
            payload={"course_id": str(course.id)},
        )
    await db.commit()
    await db.refresh(course)
    return CourseResponse.model_validate(course)


@router.put("/learn/courses/{course_id}/audience", response_model=CourseResponse)
async def set_course_audience(
    course_id: UUID,
    body: AudienceBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CourseResponse:
    await require_content_role(db, principal, "publisher")
    course = await _get_course_or_404(db, course_id)
    try:
        audience_id, _diff = await set_object_audience(
            db,
            tenant_id=principal.tenant_id,
            current_audience_id=course.audience_id,
            is_all=body.is_all,
            rules=_rule_specs(body),
            object_hint=f"{_OBJECT_TYPE}:{course.id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    course.audience_id = audience_id
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="access_change",
        object_type=_OBJECT_TYPE,
        object_id=course.id,
        object_label=course.title,
    )
    await _reindex(db, course)
    await db.commit()
    await db.refresh(course)
    return CourseResponse.model_validate(course)


@router.post("/learn/courses/{course_id}/assign", response_model=CourseResponse)
async def assign_course(
    course_id: UUID,
    body: AssignBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> CourseResponse:
    await require_content_role(db, principal, "publisher")
    course = await _get_course_or_404(db, course_id)
    for profile_id in dict.fromkeys(body.profile_ids):
        stmt = pg_insert(CourseAssignment).values(
            course_id=course_id,
            profile_id=profile_id,
            tenant_id=course.tenant_id,
            source="manual",
            assigned_by=principal.employee_id,
            due_at=body.due_at,
        )
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["course_id", "profile_id"],
                set_={"due_at": body.due_at},
            )
        )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type=_OBJECT_TYPE,
        object_id=course.id,
        object_label=course.title,
        diff={"assigned": {"old": None, "new": len(set(body.profile_ids))}},
    )
    recipients = await _employee_ids(db, list(body.profile_ids))
    if course.status == "published":
        await notify_many(
            db,
            tenant_id=course.tenant_id,
            employee_ids=list(recipients.values()),
            kind="course.assigned",
            title=course.title,
            body="Вам назначен курс — начните обучение.",
            url=f"/learn/courses/{course.id}",
            payload={"course_id": str(course.id)},
        )
    await db.commit()
    await db.refresh(course)
    return CourseResponse.model_validate(course)


# --- Уроки: CRUD -------------------------------------------------------------


@router.post("/learn/courses/{course_id}/lessons", response_model=LessonMeta, status_code=201)
async def create_lesson(
    course_id: UUID,
    body: LessonCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> LessonMeta:
    role = await require_content_role(db, principal, "author")
    course = await _get_course_or_404(db, course_id)
    _require_manage(course, principal, role)
    max_pos = (
        await db.execute(
            select(func.max(CourseLesson.position)).where(
                CourseLesson.course_id == course_id
            )
        )
    ).scalar_one()
    lesson = CourseLesson(
        tenant_id=course.tenant_id,
        course_id=course_id,
        title=body.title,
        content_format=body.content_format,
        position=(max_pos if max_pos is not None else -1) + 1,
    )
    db.add(lesson)
    await db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="create",
        object_type="course_lesson",
        object_id=lesson.id,
        object_label=f"{course.title} / {lesson.title}",
    )
    await db.commit()
    await db.refresh(lesson)
    return LessonMeta(
        id=lesson.id,
        title=lesson.title,
        position=lesson.position,
        content_format=lesson.content_format,
        unlock_rule=lesson.unlock_rule,
        status=lesson.status,
    )


@router.patch("/learn/lessons/{lesson_id}", response_model=LessonMeta)
async def update_lesson(
    lesson_id: UUID,
    body: LessonUpdate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> LessonMeta:
    role = await require_content_role(db, principal, "author")
    lesson = await _get_lesson_or_404(db, lesson_id)
    course = await _get_course_or_404(db, lesson.course_id)
    _require_manage(course, principal, role)
    fields = body.model_dump(exclude_unset=True)
    if "content" in fields and fields["content"] is not None:
        try:
            fields["content"] = validate_lesson_content(fields["content"])
        except RichContentError as e:
            raise HTTPException(status_code=422, detail=f"Содержимое: {e}") from None
    if fields.get("status") == "published" and (
        fields.get("content_format", lesson.content_format) == "pdf"
        and not (fields.get("pdf_media_id") or lesson.pdf_media_id)
    ):
        raise HTTPException(status_code=422, detail="Загрузите PDF для урока")
    for name, value in fields.items():
        setattr(lesson, name, value)
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="update",
        object_type="course_lesson",
        object_id=lesson.id,
        object_label=lesson.title,
    )
    await db.commit()
    await db.refresh(lesson)
    return LessonMeta(
        id=lesson.id,
        title=lesson.title,
        position=lesson.position,
        content_format=lesson.content_format,
        unlock_rule=lesson.unlock_rule,
        status=lesson.status,
    )


@router.delete("/learn/lessons/{lesson_id}", status_code=204)
async def delete_lesson(
    lesson_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await require_content_role(db, principal, "author")
    lesson = await _get_lesson_or_404(db, lesson_id)
    course = await _get_course_or_404(db, lesson.course_id)
    _require_manage(course, principal, role)
    if lesson.status == "published":
        has_progress = (
            await db.execute(
                select(LessonProgress.profile_id)
                .where(LessonProgress.lesson_id == lesson_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if has_progress is not None:
            raise HTTPException(
                status_code=409,
                detail="По уроку есть прогресс сотрудников — переведите его в черновик",
            )
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.employee_id,
        action="delete",
        object_type="course_lesson",
        object_id=lesson.id,
        object_label=lesson.title,
    )
    await db.delete(lesson)
    await db.commit()


@router.put("/learn/courses/{course_id}/lessons/reorder", status_code=204)
async def reorder_lessons(
    course_id: UUID,
    body: ReorderBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await require_content_role(db, principal, "author")
    course = await _get_course_or_404(db, course_id)
    _require_manage(course, principal, role)
    lessons = {
        lesson.id: lesson
        for lesson in (
            await db.execute(select(CourseLesson).where(CourseLesson.course_id == course_id))
        )
        .scalars()
        .all()
    }
    for i, lesson_id in enumerate(body.lesson_ids):
        if lesson_id in lessons:
            lessons[lesson_id].position = i
    await db.commit()


# --- Прохождение -------------------------------------------------------------


@router.get("/learn/lessons/{lesson_id}", response_model=LessonContentResponse)
async def get_lesson(
    lesson_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> LessonContentResponse:
    role = await resolve_content_role(db, principal)
    lesson = await _get_lesson_or_404(db, lesson_id)
    course = await _get_course_or_404(db, lesson.course_id)
    profile = await get_profile(db, principal)
    profile_id = profile.id if profile else None
    if not await _course_visible_to(db, course, principal, role, profile_id):
        raise HTTPException(status_code=404, detail="Урок не найден")

    manager = lifecycle.can(role, "publisher") or (
        role == "author" and course.created_by == principal.employee_id
    )
    if lesson.status != "published" and not manager:
        raise HTTPException(status_code=404, detail="Урок не найден")

    published = await _published_lessons(db, lesson.course_id)
    progress = await _progress_map(db, lesson.course_id, profile_id) if profile_id else {}
    quiz_gate = (
        await passed_required_quiz_lessons(db, lesson.course_id, profile_id)
        if profile_id and not manager
        else {}
    )

    if not manager and _lesson_locked(course, published, lesson, progress, quiz_gate):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Урок откроется после завершения предыдущих",
        )

    # Открытие урока = старт прогресса (idempotent).
    my_progress = progress.get(lesson.id)
    if profile_id and my_progress is None and lesson.status == "published":
        stmt = pg_insert(LessonProgress).values(
            profile_id=profile_id,
            lesson_id=lesson.id,
            tenant_id=lesson.tenant_id,
            course_id=lesson.course_id,
        )
        await db.execute(
            stmt.on_conflict_do_nothing(index_elements=["profile_id", "lesson_id"])
        )
        await db.commit()
        progress = await _progress_map(db, lesson.course_id, profile_id)
        my_progress = progress.get(lesson.id)

    content = None
    gate_blocks: list[str] = []
    required_videos: list[str] = []
    if lesson.content_format == "blocks" and lesson.content:
        gate_blocks = collect_gate_blocks(lesson.content)
        required_videos = collect_required_videos(lesson.content)
        # Менеджеру correct остаётся (редактор), потребителю — вырезается.
        content = prepare_for_consumer(
            lesson.content, sign_media_path, strip_correct=not manager
        )

    pdf_url = None
    if lesson.content_format == "pdf" and lesson.pdf_media_id:
        media = await db.get(MediaFile, lesson.pdf_media_id)
        if media is not None:
            pdf_url = sign_media_path(media.id)

    ordered = list(published)
    idx = next((i for i, x in enumerate(ordered) if x.id == lesson.id), None)
    prev_id = ordered[idx - 1].id if idx is not None and idx > 0 else None
    next_lesson = ordered[idx + 1] if idx is not None and idx + 1 < len(ordered) else None
    next_locked = (
        _lesson_locked(course, ordered, next_lesson, progress, quiz_gate)
        if next_lesson is not None and not manager
        else False
    )

    return LessonContentResponse(
        id=lesson.id,
        course_id=lesson.course_id,
        title=lesson.title,
        position=lesson.position,
        content_format=lesson.content_format,
        content=content,
        pdf_url=pdf_url,
        forbid_download=lesson.forbid_download,
        unlock_rule=lesson.unlock_rule,
        status=lesson.status,
        completed=bool(my_progress and my_progress.status == "completed"),
        block_state=dict(my_progress.block_state) if my_progress else {},
        gate_blocks=gate_blocks,
        required_videos=required_videos,
        prev_lesson_id=prev_id,
        next_lesson_id=next_lesson.id if next_lesson else None,
        next_locked=next_locked,
    )


async def _locked_progress(
    db: AsyncSession, profile_id: UUID, lesson_id: UUID
) -> LessonProgress:
    row = (
        await db.execute(
            select(LessonProgress)
            .where(
                LessonProgress.profile_id == profile_id,
                LessonProgress.lesson_id == lesson_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=409, detail="Сначала откройте урок")
    return row


@router.post("/learn/lessons/{lesson_id}/blocks/{block_id}/answer")
async def answer_block(
    lesson_id: UUID,
    block_id: str,
    body: BlockAnswerBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    lesson = await _get_lesson_or_404(db, lesson_id)
    profile = await get_profile(db, principal)
    if profile is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    if not lesson.content:
        raise HTTPException(status_code=404, detail="Блок не найден")
    correct = check_answer(lesson.content, block_id, body.answer)
    if correct is None:
        raise HTTPException(status_code=404, detail="Блок не найден")

    progress = await _locked_progress(db, profile.id, lesson_id)
    state = dict(progress.block_state)
    answers = dict(state.get("answers") or {})
    answers[block_id] = {"answer": body.answer, "correct": correct}
    state["answers"] = answers
    progress.block_state = state
    await db.commit()
    return {"correct": correct}


@router.post("/learn/lessons/{lesson_id}/video-progress", status_code=204)
async def video_progress(
    lesson_id: UUID,
    body: VideoProgressBody,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    profile = await get_profile(db, principal)
    if profile is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    progress = await _locked_progress(db, profile.id, lesson_id)
    state = dict(progress.block_state)
    videos = dict(state.get("video") or {})
    entry = dict(videos.get(str(body.media_id)) or {})
    merged = merge_intervals(list(entry.get("intervals") or []), body.intervals)
    videos[str(body.media_id)] = {"intervals": merged, "duration": body.duration}
    state["video"] = videos
    progress.block_state = state
    await db.commit()


@router.post("/learn/lessons/{lesson_id}/complete", response_model=LessonContentResponse)
async def complete_lesson(
    lesson_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> LessonContentResponse:
    await enforce_rate_limit(
        bucket="lesson:complete",
        employee_id=str(principal.employee_id),
        limit=60,
        window_sec=60,
    )
    lesson = await _get_lesson_or_404(db, lesson_id)
    profile = await get_profile(db, principal)
    if profile is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    progress = await _locked_progress(db, profile.id, lesson_id)

    if progress.status != "completed":
        state = progress.block_state or {}
        # Предусловие 1: gate-вопросы отвечены.
        if lesson.content:
            answers = state.get("answers") or {}
            missing = [b for b in collect_gate_blocks(lesson.content) if b not in answers]
            if missing:
                raise HTTPException(
                    status_code=409,
                    detail="Ответьте на контрольные вопросы урока",
                )
            # Предусловие 2: обязательные видео досмотрены (≥90%).
            videos = state.get("video") or {}
            for media_id in collect_required_videos(lesson.content):
                entry = videos.get(media_id) or {}
                if not is_watched(
                    list(entry.get("intervals") or []), float(entry.get("duration") or 0)
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Досмотрите обязательное видео до конца",
                    )
        progress.status = "completed"
        progress.completed_at = datetime.now(UTC)
        await db.flush()  # autoflush=False: счётчик в _update_course_progress
        course = await _get_course_or_404(db, lesson.course_id)
        await _update_course_progress(db, course, profile.id)
        # Рейтинг (Ф3b): идемпотентное «первое действие».
        await award(
            db,
            tenant_id=course.tenant_id,
            profile_id=profile.id,
            event_type="lesson.completed",
            object_type="course_lesson",
            object_id=lesson.id,
        )
        # Завершил курс → сертификат (если включён у курса).
        completed_at = (
            await db.execute(
                select(CourseProgress.completed_at).where(
                    CourseProgress.course_id == course.id,
                    CourseProgress.profile_id == profile.id,
                )
            )
        ).scalar_one_or_none()
        if completed_at is not None:
            await issue_if_earned(db, course, profile)
        await db.commit()

    return await get_lesson(lesson_id, principal, db)  # свежий ответ с замками


# --- Шаблоны -----------------------------------------------------------------


@router.get("/learn/lesson-templates", response_model=list[TemplateResponse])
async def list_templates(
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateResponse]:
    await require_content_role(db, principal, "author")
    rows = (
        (await db.execute(select(LessonTemplate).order_by(LessonTemplate.title)))
        .scalars()
        .all()
    )
    return [TemplateResponse.model_validate(t) for t in rows]


@router.post("/learn/lesson-templates", response_model=TemplateResponse, status_code=201)
async def create_template(
    body: TemplateCreate,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    await require_content_role(db, principal, "author")
    try:
        content = validate_lesson_content(body.content)
    except RichContentError as e:
        raise HTTPException(status_code=422, detail=f"Содержимое: {e}") from None
    template = LessonTemplate(
        tenant_id=principal.tenant_id,
        title=body.title,
        content=content,
        created_by=principal.employee_id,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return TemplateResponse.model_validate(template)


@router.delete("/learn/lesson-templates/{template_id}", status_code=204)
async def delete_template(
    template_id: UUID,
    principal: Principal = Depends(require_auth()),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_content_role(db, principal, "publisher")
    template = await db.get(LessonTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    await db.delete(template)
    await db.commit()
