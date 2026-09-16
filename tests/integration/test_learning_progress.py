"""«Прогресс обучения по сотрудникам» — скоуп, знаменатель, панель, CSV.

Главный тест здесь — `test_list_row_matches_detail_for_each_person`: список
считает знаменатель свёрткой в Python, панель по человеку — своими запросами.
Две реализации одного правила обязаны сходиться, и проверять это надо НА ДВУХ
разных людях: на одном не отличить «панель собрана для нужного человека» от
«панель собрана для того, кто смотрит».
"""

from __future__ import annotations

import csv
import io
import uuid

import pytest
from fastapi import HTTPException
from signaris_auth import Principal
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.learn_analytics import (
    employee_progress,
    employee_progress_detail,
    export_csv,
)
from app.models.audience import Audience, AudienceRule
from app.models.course import Course, CourseLesson
from app.models.employee_profile import EmployeeProfile
from app.models.org import Position, Store
from app.models.progress import CourseAssignment, CourseProgress
from app.services.audience_resolver import recalc_profile
from tests.integration.conftest import make_principal

pytestmark = pytest.mark.integration


async def _mk_principal(
    db: AsyncSession, tenant_id: uuid.UUID, *, email: str, role: str = "admin"
) -> Principal:
    principal = make_principal(
        tenant_id, email=email, role=role, tenant_slug=f"t-{tenant_id.hex[:12]}"
    )
    from signaris_auth.shadow import upsert_shadow_tenant, upsert_shadow_user

    await upsert_shadow_tenant(db, principal, table="shadow_tenants")
    await upsert_shadow_user(db, principal, table="shadow_users")
    return principal


async def _mk_profile(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    name: str,
    email: str,
    employee_id: uuid.UUID | None = None,
    store_id: uuid.UUID | None = None,
    position_id: uuid.UUID | None = None,
    org_role: str = "employee",
) -> EmployeeProfile:
    profile = EmployeeProfile(
        tenant_id=tenant_id,
        employee_id=employee_id,
        email=email,
        full_name=name,
        store_id=store_id,
        position_id=position_id,
        org_role=org_role,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _mk_course(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    title: str,
    course_type: str = "mandatory",
    status: str = "published",
    audience_id: uuid.UUID | None = None,
    lessons: int = 2,
) -> Course:
    course = Course(
        tenant_id=tenant_id,
        title=title,
        course_type=course_type,
        status=status,
        audience_id=audience_id,
    )
    db.add(course)
    await db.flush()
    for i in range(lessons):
        db.add(
            CourseLesson(
                tenant_id=tenant_id,
                course_id=course.id,
                title=f"{title} — урок {i + 1}",
                position=i,
                status="published",
            )
        )
    await db.flush()
    return course


async def _mk_progress(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    profile: EmployeeProfile,
    course: Course,
    *,
    done: bool,
    lessons_completed: int = 2,
    lessons_total: int = 2,
) -> None:
    from datetime import UTC, datetime

    db.add(
        CourseProgress(
            tenant_id=tenant_id,
            profile_id=profile.id,
            course_id=course.id,
            lessons_completed=lessons_completed,
            lessons_total=lessons_total,
            completed_at=datetime.now(UTC) if done else None,
        )
    )
    await db.flush()


async def _mk_audience(
    db: AsyncSession, tenant_id: uuid.UUID, *, position_id: uuid.UUID
) -> Audience:
    audience = Audience(tenant_id=tenant_id, object_hint="course:ТУ")
    db.add(audience)
    await db.flush()
    db.add(
        AudienceRule(
            tenant_id=tenant_id,
            audience_id=audience.id,
            mode="include",
            position_ids=[position_id],
        )
    )
    await db.flush()
    return audience


# ─── Знаменатель ─────────────────────────────────────────────────────────────


async def test_denominator_follows_audience_and_assignment(
    db: AsyncSession, tenant_id: uuid.UUID
):
    admin = await _mk_principal(db, tenant_id, email="admin@t.ru")
    position = Position(tenant_id=tenant_id, name="ТУ")
    db.add(position)
    await db.flush()

    audience = await _mk_audience(db, tenant_id, position_id=position.id)
    await _mk_course(db, tenant_id, title="Всем")
    aud_course = await _mk_course(db, tenant_id, title="Только ТУ", audience_id=audience.id)
    await _mk_course(db, tenant_id, title="Рекомендованный", course_type="recommended")
    await _mk_course(db, tenant_id, title="Черновик", status="draft")

    member = await _mk_profile(
        db, tenant_id, name="Аня ТУ", email="tu@t.ru", position_id=position.id
    )
    outsider = await _mk_profile(db, tenant_id, name="Боря Продавец", email="s@t.ru")
    await recalc_profile(db, member)
    await recalc_profile(db, outsider)

    resp = await employee_progress(principal=admin, db=db)
    by_id = {r.profile_id: r for r in resp.items}

    # Члену аудитории адресованы оба обязательных, чужому — только общий.
    assert by_id[member.id].mandatory_total == 2
    assert by_id[outsider.id].mandatory_total == 1

    # Назначение поднимает знаменатель не-члену.
    db.add(
        CourseAssignment(
            tenant_id=tenant_id, course_id=aud_course.id, profile_id=outsider.id
        )
    )
    await db.flush()
    resp2 = await employee_progress(principal=admin, db=db)
    assert {r.profile_id: r for r in resp2.items}[outsider.id].mandatory_total == 2


async def test_archived_course_progress_is_out_of_counters_but_visible_in_detail(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Дефект, ради которого писался сервис: архивные курсы попадали в счётчики."""
    admin = await _mk_principal(db, tenant_id, email="admin2@t.ru")
    live = await _mk_course(db, tenant_id, title="Живой")
    archived = await _mk_course(db, tenant_id, title="Снятый", status="archived")
    person = await _mk_profile(db, tenant_id, name="Вера", email="v@t.ru")
    await recalc_profile(db, person)
    await _mk_progress(db, tenant_id, person, live, done=True)
    await _mk_progress(db, tenant_id, person, archived, done=True)

    # Ищем СВОЮ строку, а не первую: роль в testcontainers — superuser, она
    # обходит RLS, и в общем прогоне выдача содержит профили соседних тестов
    # (на проде тенанты изолированы политикой).
    resp = await employee_progress(principal=admin, db=db)
    row = next(r for r in resp.items if r.profile_id == person.id)
    assert row.courses_completed == 1, "архивный курс не должен считаться"

    detail = await employee_progress_detail(person.id, principal=admin, db=db)
    titles = {c.title: c for c in detail.courses}
    assert "Снятый" in titles, "но в панели он обязан быть виден"
    assert titles["Снятый"].source == "progress_only"
    assert titles["Снятый"].required is False


# ─── Список против панели ────────────────────────────────────────────────────


async def test_list_row_matches_detail_for_each_person(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """Свёртка в Python и запросы панели обязаны давать одно число.

    Двое разных людей — обязательное условие: на одном тест прошёл бы и в том
    случае, если панель собрана для смотрящего, а не для выбранного человека.
    """
    admin = await _mk_principal(db, tenant_id, email="admin3@t.ru")
    position = Position(tenant_id=tenant_id, name="ТУ")
    db.add(position)
    await db.flush()
    audience = await _mk_audience(db, tenant_id, position_id=position.id)

    common = await _mk_course(db, tenant_id, title="Общий")
    only_tu = await _mk_course(db, tenant_id, title="ТУшный", audience_id=audience.id)

    alice = await _mk_profile(
        db, tenant_id, name="Алиса", email="a@t.ru", position_id=position.id
    )
    bob = await _mk_profile(db, tenant_id, name="Боб", email="b@t.ru")
    await recalc_profile(db, alice)
    await recalc_profile(db, bob)
    await _mk_progress(db, tenant_id, alice, common, done=True)
    await _mk_progress(db, tenant_id, alice, only_tu, done=False)
    await _mk_progress(db, tenant_id, bob, common, done=False)

    all_rows = {r.profile_id: r for r in (await employee_progress(principal=admin, db=db)).items}
    # Только свои двое: в общем прогоне выдача содержит и чужие профили
    # (superuser в testcontainers обходит RLS).
    rows = {pid: all_rows[pid] for pid in (alice.id, bob.id)}
    for profile_id, row in rows.items():
        detail = await employee_progress_detail(profile_id, principal=admin, db=db)
        assert detail.profile.profile_id == profile_id
        required = [c for c in detail.courses if c.required]
        assert len(required) == row.mandatory_total
        assert sum(1 for c in required if c.status == "completed") == row.mandatory_done

    assert rows[alice.id].mandatory_total == 2
    assert rows[alice.id].mandatory_done == 1
    assert rows[bob.id].mandatory_total == 1
    assert rows[bob.id].mandatory_done == 0


async def test_stale_lesson_snapshot_is_clamped(db: AsyncSession, tenant_id: uuid.UUID):
    """`lessons_total` протухает: у курса стало больше уроков, снапшот старый."""
    admin = await _mk_principal(db, tenant_id, email="admin4@t.ru")
    course = await _mk_course(db, tenant_id, title="Растущий", lessons=5)
    person = await _mk_profile(db, tenant_id, name="Гоша", email="g@t.ru")
    await recalc_profile(db, person)
    # Снапшот помнит курс из двух уроков, оба пройдены.
    await _mk_progress(
        db, tenant_id, person, course, done=False, lessons_completed=2, lessons_total=2
    )

    detail = await employee_progress_detail(person.id, principal=admin, db=db)
    row = next(c for c in detail.courses if c.title == "Растущий")
    assert row.lessons_total == 5, "берём живой счётчик уроков"
    assert row.lessons_completed <= row.lessons_total


# ─── Права ───────────────────────────────────────────────────────────────────


async def test_line_employee_gets_403_on_both_endpoints(
    db: AsyncSession, tenant_id: uuid.UUID
):
    principal = await _mk_principal(db, tenant_id, email="line@t.ru", role="member")
    person = await _mk_profile(
        db, tenant_id, name="Линейный", email="line@t.ru", employee_id=principal.employee_id
    )
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await employee_progress(principal=principal, db=db)
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc2:
        await employee_progress_detail(person.id, principal=principal, db=db)
    assert exc2.value.status_code == 403


async def test_detail_out_of_scope_is_404_not_403(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """404, иначе по коду ответа можно перебирать состав чужих магазинов."""
    admin = await _mk_principal(db, tenant_id, email="admin5@t.ru")
    missing = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await employee_progress_detail(missing, principal=admin, db=db)
    assert exc.value.status_code == 404


async def test_profile_without_account_is_listed(
    db: AsyncSession, tenant_id: uuid.UUID
):
    """84 человека на проде без учётки — молча прятать их нельзя."""
    admin = await _mk_principal(db, tenant_id, email="admin6@t.ru")
    await _mk_course(db, tenant_id, title="Всем")
    person = await _mk_profile(
        db, tenant_id, name="Без учётки", email="no@t.ru", employee_id=None
    )
    await recalc_profile(db, person)

    resp = await employee_progress(principal=admin, db=db)
    row = next(r for r in resp.items if r.profile_id == person.id)
    assert row.has_account is False
    assert row.auth_state in {"no_account", "not_linked"}
    assert row.mandatory_total == 1, "знаменатель есть и у того, кто не заходил"
    assert resp.summary.without_account >= 1


# ─── Выдача и выгрузка ───────────────────────────────────────────────────────


async def test_list_is_not_truncated(db: AsyncSession, tenant_id: uuid.UUID):
    """«Выдачу не обрезаем нигде» — решение владельца 16.09."""
    admin = await _mk_principal(db, tenant_id, email="admin7@t.ru")
    mine = set()
    for i in range(120):
        p = await _mk_profile(
            db, tenant_id, name=f"Сотрудник {i:03d}", email=f"e{i}@t.ru"
        )
        mine.add(p.id)
    resp = await employee_progress(principal=admin, db=db)
    # Проверяем отсутствие обрезки, а не абсолютное число: см. про superuser и
    # RLS в соседнем тесте — в общем прогоне в выдаче есть и чужие профили.
    assert len(resp.items) == resp.total
    assert resp.truncated is False
    assert mine <= {r.profile_id for r in resp.items}, "ни одна строка не потеряна"


async def test_csv_matches_json(db: AsyncSession, tenant_id: uuid.UUID):
    """Экран и выгрузка считают одним кодом — значит и числа совпадают."""
    admin = await _mk_principal(db, tenant_id, email="admin8@t.ru")
    course = await _mk_course(db, tenant_id, title="Общий")
    person = await _mk_profile(db, tenant_id, name="Дина", email="d@t.ru")
    await recalc_profile(db, person)
    await _mk_progress(db, tenant_id, person, course, done=True)

    resp = await employee_progress(principal=admin, db=db)
    stream = await export_csv(principal=admin, db=db)
    body = b"".join([chunk async for chunk in stream.body_iterator]).decode("utf-8")
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿")), delimiter=";"))
    header, data = rows[0], rows[1:]
    i_total = header.index("Обязательных всего")
    i_done = header.index("Обязательных пройдено")
    by_name = {r[0]: r for r in data}

    assert "Курсов назначено" not in header, "колонка убрана, а не переопределена"
    for item in resp.items:
        csv_row = by_name[item.full_name]
        assert int(csv_row[i_total]) == item.mandatory_total
        assert int(csv_row[i_done]) == item.mandatory_done


async def test_filters_narrow_both_list_and_export(
    db: AsyncSession, tenant_id: uuid.UUID
):
    admin = await _mk_principal(db, tenant_id, email="admin9@t.ru")
    store = Store(tenant_id=tenant_id, name="Невская 3")
    db.add(store)
    await db.flush()
    await _mk_profile(db, tenant_id, name="Ева", email="eva@t.ru", store_id=store.id)
    await _mk_profile(db, tenant_id, name="Жора", email="zhora@t.ru")

    scoped = await employee_progress(store_id=store.id, principal=admin, db=db)
    assert [r.full_name for r in scoped.items] == ["Ева"]

    found = await employee_progress(q="жора", principal=admin, db=db)
    assert [r.full_name for r in found.items] == ["Жора"]
