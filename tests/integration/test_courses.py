"""Integration-тесты курсов (Ф3a): замки, монотонность, гейты завершения,
иммутабельность course_progress, видимость по назначению, hook granted_at."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from signaris_auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.courses import (
    _course_visible_to,
    answer_block,
    complete_lesson,
    get_lesson,
    list_courses,
    video_progress,
)
from app.models.audience import Audience, AudienceRule
from app.models.course import Course, CourseLesson
from app.models.employee_profile import EmployeeProfile
from app.models.notification import Notification
from app.models.org import Position
from app.models.progress import CourseAssignment, CourseProgress, LessonProgress
from app.schemas.course import BlockAnswerBody, VideoProgressBody
from app.services.audience_resolver import recalc_profile
from app.services.learn_notify import notify_new_audience_members
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_redis_no_push(monkeypatch):
    """Rate-limit требует Redis, пуши — фоновые задачи: в тестах глушим."""

    async def _noop_rate_limit(**kw) -> None:
        return None

    from app.api import courses as courses_api
    from app.services import notify_batch

    monkeypatch.setattr(courses_api, "enforce_rate_limit", _noop_rate_limit)
    monkeypatch.setattr(notify_batch, "_schedule_push_batch", lambda **kw: None)


async def _mk_member(
    db: AsyncSession, tenant_id: uuid.UUID, email: str = "seller@t.ru"
) -> tuple[Principal, EmployeeProfile]:
    # Уникальный slug: endpoint-функции коммитят, shadow_tenants.slug UNIQUE.
    principal = make_principal(tenant_id, email=email, tenant_slug=f"t-{tenant_id.hex[:12]}")
    from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user

    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    profile = EmployeeProfile(
        tenant_id=tenant_id,
        employee_id=principal.employee_id,
        email=email,
        full_name="Продавец Тестовый",
    )
    db.add(profile)
    await db.flush()
    return principal, profile


async def _mk_course(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    lesson_count: int = 2,
    progression_mode: str = "sequential",
    lesson_content: dict | None = None,
    **kw,
) -> tuple[Course, list[CourseLesson]]:
    course = Course(
        tenant_id=tenant_id,
        title=kw.pop("title", "Стандарты сервиса"),
        progression_mode=progression_mode,
        status="published",
        **kw,
    )
    db.add(course)
    await db.flush()
    lessons = []
    for i in range(lesson_count):
        lesson = CourseLesson(
            tenant_id=tenant_id,
            course_id=course.id,
            title=f"Урок {i + 1}",
            position=i,
            status="published",
            content=lesson_content,
        )
        db.add(lesson)
        lessons.append(lesson)
    await db.flush()
    return course, lessons


VIDEO_ID = str(uuid.uuid4())

GATED_CONTENT = {
    "schema": 1,
    "doc": {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Смотри и отвечай"}]},
            {
                "type": "video",
                "attrs": {"mediaId": VIDEO_ID, "requireFullWatch": True},
            },
            {
                "type": "checkQuestion",
                "attrs": {
                    "blockId": "q1",
                    "question": "Как приветствуем гостя?",
                    "options": ["Молча", "Улыбкой и здороваемся"],
                    "correct": 1,
                    "gateNext": True,
                },
            },
        ],
    },
}


async def test_sequential_locks_enforced_server_side(
    db: AsyncSession, tenant_id: uuid.UUID
):
    principal, _profile = await _mk_member(db, tenant_id)
    _course, lessons = await _mk_course(db, tenant_id, lesson_count=2)

    # Урок 2 заперт, пока урок 1 не завершён.
    with pytest.raises(HTTPException) as exc:
        await get_lesson(lessons[1].id, principal, db)
    assert exc.value.status_code == 403

    resp1 = await get_lesson(lessons[0].id, principal, db)
    assert not resp1.completed and resp1.next_locked

    done = await complete_lesson(lessons[0].id, principal, db)
    assert done.completed

    resp2 = await get_lesson(lessons[1].id, principal, db)
    assert resp2.prev_lesson_id == lessons[0].id


async def test_free_mode_no_locks(db: AsyncSession, tenant_id: uuid.UUID):
    principal, _profile = await _mk_member(db, tenant_id)
    _course, lessons = await _mk_course(db, tenant_id, progression_mode="free")
    resp = await get_lesson(lessons[1].id, principal, db)
    assert resp.id == lessons[1].id


async def test_monotonicity_inserted_lesson_does_not_relock(
    db: AsyncSession, tenant_id: uuid.UUID
):
    principal, _profile = await _mk_member(db, tenant_id)
    course, lessons = await _mk_course(db, tenant_id, lesson_count=2)
    await get_lesson(lessons[0].id, principal, db)
    await complete_lesson(lessons[0].id, principal, db)
    await get_lesson(lessons[1].id, principal, db)  # старт второго урока

    # Автор вставил новый урок ПЕРЕД вторым — начатый урок не запирается.
    inserted = CourseLesson(
        tenant_id=tenant_id,
        course_id=course.id,
        title="Вводный (добавлен позже)",
        position=0,
        status="published",
    )
    for lesson in lessons:
        lesson.position += 1
    db.add(inserted)
    await db.flush()

    resp = await get_lesson(lessons[1].id, principal, db)  # не 403
    assert resp.id == lessons[1].id
    # А вот новый урок теперь первый незавершённый — и сам открыт.
    resp_new = await get_lesson(inserted.id, principal, db)
    assert resp_new.id == inserted.id


async def test_complete_gates_video_and_question(
    db: AsyncSession, tenant_id: uuid.UUID
):
    principal, profile = await _mk_member(db, tenant_id)
    course, lessons = await _mk_course(
        db, tenant_id, lesson_count=1, lesson_content=GATED_CONTENT
    )
    lesson = lessons[0]

    opened = await get_lesson(lesson.id, principal, db)
    assert opened.gate_blocks == ["q1"]
    assert opened.required_videos == [VIDEO_ID]
    # Потребителю correct не отдаётся, src подписан.
    nodes = opened.content["doc"]["content"]
    assert "correct" not in nodes[2]["attrs"]
    assert nodes[1]["attrs"]["src"].startswith(f"/api/media/{VIDEO_ID}?e=")

    # Гейт-вопрос не отвечен → 409.
    with pytest.raises(HTTPException) as exc:
        await complete_lesson(lesson.id, principal, db)
    assert exc.value.status_code == 409
    assert "вопрос" in exc.value.detail.lower()

    result = await answer_block(lesson.id, "q1", BlockAnswerBody(answer=1), principal, db)
    assert result == {"correct": True}

    # Видео досмотрено лишь наполовину → 409.
    await video_progress(
        lesson.id,
        VideoProgressBody(media_id=uuid.UUID(VIDEO_ID), intervals=[[0, 50]], duration=100),
        principal,
        db,
    )
    with pytest.raises(HTTPException) as exc:
        await complete_lesson(lesson.id, principal, db)
    assert exc.value.status_code == 409
    assert "видео" in exc.value.detail.lower()

    # Досмотр (два куска с разных устройств суммарно ≥90%) → завершение.
    await video_progress(
        lesson.id,
        VideoProgressBody(media_id=uuid.UUID(VIDEO_ID), intervals=[[45, 95]], duration=100),
        principal,
        db,
    )
    done = await complete_lesson(lesson.id, principal, db)
    assert done.completed

    progress = (
        await db.execute(
            select(CourseProgress).where(
                CourseProgress.course_id == course.id,
                CourseProgress.profile_id == profile.id,
            )
        )
    ).scalar_one()
    assert progress.completed_at is not None
    assert progress.lessons_completed == 1 and progress.lessons_total == 1


async def test_course_completed_at_immutable(db: AsyncSession, tenant_id: uuid.UUID):
    principal, profile = await _mk_member(db, tenant_id)
    course, lessons = await _mk_course(db, tenant_id, lesson_count=1)
    await get_lesson(lessons[0].id, principal, db)
    await complete_lesson(lessons[0].id, principal, db)

    progress = (
        await db.execute(
            select(CourseProgress).where(
                CourseProgress.course_id == course.id,
                CourseProgress.profile_id == profile.id,
            )
        )
    ).scalar_one()
    first_completed_at = progress.completed_at
    assert first_completed_at is not None

    # Добавили новый урок — завершение не отбирается (ревью §13).
    late = CourseLesson(
        tenant_id=tenant_id,
        course_id=course.id,
        title="Дополнение",
        position=1,
        status="published",
    )
    db.add(late)
    await db.flush()

    from app.api.courses import _update_course_progress

    await _update_course_progress(db, course, profile.id)
    await db.flush()
    db.expire(progress)
    progress = (
        await db.execute(
            select(CourseProgress).where(
                CourseProgress.course_id == course.id,
                CourseProgress.profile_id == profile.id,
            )
        )
    ).scalar_one()
    assert progress.completed_at == first_completed_at
    assert progress.lessons_total == 2 and progress.lessons_completed == 1


async def test_assignment_implies_visibility(db: AsyncSession, tenant_id: uuid.UUID):
    principal, profile = await _mk_member(db, tenant_id)

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    course, _lessons = await _mk_course(db, tenant_id, audience_id=audience.id)

    # Не член аудитории (audience_members пуста) → курс невидим.
    assert not await _course_visible_to(db, course, principal, "none", profile.id)

    db.add(
        CourseAssignment(
            course_id=course.id,
            profile_id=profile.id,
            tenant_id=tenant_id,
            source="manual",
        )
    )
    await db.flush()

    # Личное назначение = имплицитная видимость (ревью §8).
    assert await _course_visible_to(db, course, principal, "none", profile.id)
    listing = await list_courses(False, principal, db)
    ids = [c.id for c in listing.items]
    assert course.id in ids
    assert next(c for c in listing.items if c.id == course.id).enrolled


async def test_granted_hook_notifies_mandatory_course(
    db: AsyncSession, tenant_id: uuid.UUID, monkeypatch
):
    from app.services import notification_dispatcher

    monkeypatch.setattr(notification_dispatcher, "schedule_push", lambda **kw: None)

    seller_pos = Position(tenant_id=tenant_id, name="Продавец")
    db.add(seller_pos)
    await db.flush()

    principal, profile = await _mk_member(db, tenant_id, email="newbie@t.ru")

    audience = Audience(tenant_id=tenant_id)
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            position_ids=[seller_pos.id],
        )
    )
    await _mk_course(
        db,
        tenant_id,
        audience_id=audience.id,
        course_type="mandatory",
        title="Онбординг продавца",
    )
    await db.flush()

    profile.position_id = seller_pos.id
    await db.flush()
    diffs = await recalc_profile(db, profile)
    await notify_new_audience_members(db, diffs)
    await db.flush()

    notif = (
        await db.execute(
            select(Notification).where(
                Notification.employee_id == principal.employee_id,
                Notification.kind == "course.assigned",
            )
        )
    ).scalar_one()
    assert notif.title == "Онбординг продавца"


async def test_lesson_progress_started_on_open(db: AsyncSession, tenant_id: uuid.UUID):
    principal, profile = await _mk_member(db, tenant_id)
    _course, lessons = await _mk_course(db, tenant_id, lesson_count=1)
    await get_lesson(lessons[0].id, principal, db)
    row = (
        await db.execute(
            select(LessonProgress).where(
                LessonProgress.lesson_id == lessons[0].id,
                LessonProgress.profile_id == profile.id,
            )
        )
    ).scalar_one()
    assert row.status == "in_progress"
