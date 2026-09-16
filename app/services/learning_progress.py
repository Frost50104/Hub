"""Прогресс обучения по сотрудникам — ОДИН счётчик на экран, панель и выгрузку.

Зачем отдельный модуль, а не запросы в ручке. До 16.09 персональные цифры
существовали ровно в одном месте — CSV-выгрузке `learn_analytics.export_csv`, —
и считались там неверно дважды:

* «Курсов назначено» было `COUNT(course_assignments)`, а таких строк на проде
  одна на весь тенант: колонка почти у всех показывала ноль. Сотрудник при этом
  видит у себя курс по ДРУГОМУ правилу — `courses.py::list_courses` считает
  `enrolled = назначен ИЛИ есть прогресс ИЛИ обязательный` по курсам, видимым
  через `audience_resolver.visible_filter`.
* счётчики `course_progress` не джойнились к `courses`, поэтому в «начато» и
  «завершено» попадали архивные и черновые курсы (на проде 18 строк) — отсюда
  «17 завершённых при 16 опубликованных».

Экран руководителя и «Моё обучение» сотрудника обязаны называть одно число
одинаково, иначе экрану перестают верить целиком. Поэтому правило живёт здесь
в ЧИСТЫХ функциях, а ручка списка, ручка панели и CSV зовут один сборщик.

Почему свёртка в Python, а не один коррелированный запрос. Знаменатель
«обязательных N» — главное число экрана, а интеграционные тесты в CI не бегут
(`-m "not integration"`, см. `tests/unit/test_stats_sql_compiles.py`). Чистая
функция попадает под юнит-тест, выражение внутри `select` — нет. Цена невелика:
на проде это 16 курсов, 64 строки членства в аудиториях и 344 строки прогресса.

Панель по ОДНОМУ человеку при этом зовёт `visible_filter` буквально, с
конкретным UUID; интеграционный тест сверяет, что обе ветки дают одно и то же.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent, Certificate
from app.models.audience import AudienceMember
from app.models.course import Course, CourseLesson
from app.models.employee_profile import EmployeeProfile
from app.models.org import Position, Store
from app.models.progress import CourseAssignment, CourseProgress
from app.models.quiz import Quiz, QuizAttempt
from app.models.shadow import ShadowUser
from app.services.people_search import match_condition

#: Потолок строк ответа. Совпадает с `_EXPORT_ROW_LIMIT` намеренно: два потолка
#: разъедутся, и экран с выгрузкой начнут показывать разное.
ROWS_HARD_CAP = 5000

#: Последних попыток тестов в панели по человеку.
DETAIL_ATTEMPTS = 20

_EMPTY = UUID(int=0)  # sentinel для пустого IN (конвенция репозитория)


# ─── Чистые правила ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CourseRef:
    """Курс каталога — ровно те поля, от которых зависит адресация."""

    id: UUID
    title: str
    course_type: str
    status: str
    audience_id: UUID | None


@dataclass(frozen=True, slots=True)
class ProgressRef:
    """Строка `course_progress`. Статуса в таблице нет — он выводится."""

    course_id: UUID
    lessons_completed: int
    lessons_total: int
    started_at: datetime | None
    completed_at: datetime | None


def course_status(progress: ProgressRef | None) -> str:
    """`not_started` | `in_progress` | `completed`.

    Строки нет — не начат. `completed_at` иммутабелен (`courses.py` пишет его
    через `coalesce`), поэтому он и решает: курс, закрытый до добавления новых
    уроков, остаётся завершённым, даже если уроков теперь больше.
    """
    if progress is None:
        return "not_started"
    if progress.completed_at is not None:
        return "completed"
    return "in_progress"


def attempt_state(
    *,
    finished_at: datetime | None,
    needs_review: bool,
    reviewed_at: datetime | None,
    passed: bool | None,
) -> str:
    """Состояние попытки словарём отчёта аттестаций.

    Порядок веток важен: у попытки на ручной проверке `passed` ещё `None`, и
    без ветки `pending_review` она молча числилась бы проваленной.
    """
    if finished_at is None:
        return "in_progress"
    if needs_review and reviewed_at is None:
        return "pending_review"
    if passed is True:
        return "passed"
    return "failed"


def pct(done: int, total: int) -> int | None:
    """Доля в процентах; `None` — «нечего проходить», а не ноль.

    `0 из 0` и `0 из 6` — разные факты: первый про человека, которому курсы не
    адресованы, второй про того, кто их не начал.
    """
    if total <= 0:
        return None
    return round(min(done, total) / total * 100)


def mandatory_course_ids(
    courses: list[CourseRef],
    member_audience_ids: set[UUID],
    assigned_ids: set[UUID],
) -> set[UUID]:
    """Обязательные курсы, адресованные человеку, — знаменатель «X из N».

    Назначение включаем: назначенный курс сотрудник видит у себя даже вне
    аудитории (`courses.py::list_courses` добавляет его вторым проходом), и
    знаменатель руководителя обязан это учитывать.
    """
    return {
        c.id
        for c in courses
        if c.status == "published"
        and c.course_type == "mandatory"
        and (
            c.audience_id is None
            or c.audience_id in member_audience_ids
            or c.id in assigned_ids
        )
    }


def enrolled_course_ids(
    courses: list[CourseRef],
    member_audience_ids: set[UUID],
    assigned_ids: set[UUID],
    progress_ids: set[UUID],
) -> set[UUID]:
    """Курсы, которые человек видит в «Моём обучении» — зеркало `courses.py:454`.

    `enrolled = назначен ИЛИ есть прогресс ИЛИ обязательный` по множеству
    видимых (аудитория) плюс назначенных.
    """
    out: set[UUID] = set()
    for c in courses:
        if c.status != "published":
            continue
        assigned = c.id in assigned_ids
        visible = c.audience_id is None or c.audience_id in member_audience_ids
        if assigned or (
            visible and (c.course_type == "mandatory" or c.id in progress_ids)
        ):
            out.add(c.id)
    return out


@dataclass(slots=True)
class LearningRow:
    """Строка экрана и строка CSV — одна и та же величина."""

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
    courses_available: int
    courses_started: int
    courses_completed: int
    quizzes_passed: int
    certificates: int
    points: float
    last_activity_at: datetime | None

    @property
    def mandatory_pct(self) -> int | None:
        return pct(self.mandatory_done, self.mandatory_total)


@dataclass(slots=True)
class LearningSummary:
    people: int
    without_account: int
    never_active: int
    completed_all: int
    completed_none: int
    mandatory_total: int
    mandatory_done: int
    mandatory_pct: int | None


def summarize(rows: list[LearningRow]) -> LearningSummary:
    """Сводка над теми же строками, что видит человек.

    `completed_all`/`completed_none` считаются ТОЛЬКО по тем, кому есть что
    проходить: иначе офисные сотрудники вне обязательных аудиторий раздули бы
    «завершили всё» на ровном месте.
    """
    with_mandatory = [r for r in rows if r.mandatory_total > 0]
    total = sum(r.mandatory_total for r in rows)
    done = sum(min(r.mandatory_done, r.mandatory_total) for r in rows)
    return LearningSummary(
        people=len(rows),
        without_account=sum(1 for r in rows if not r.has_account),
        never_active=sum(1 for r in rows if r.last_activity_at is None),
        completed_all=sum(
            1 for r in with_mandatory if r.mandatory_done >= r.mandatory_total
        ),
        completed_none=sum(1 for r in with_mandatory if r.mandatory_done == 0),
        mandatory_total=total,
        mandatory_done=done,
        mandatory_pct=pct(done, total),
    )


# ─── Билдеры запросов (юнит-тест на компиляцию) ──────────────────────────────


def profiles_filter(profile_ids: list[UUID] | None, status: str = "active"):
    """WHERE по скоупу. `None` = вся сеть (RLS уже режет по тенанту).

    Кассы точек отсекаются ТОЛЬКО в ветке «вся сеть». В ветке по явным id
    предикат ставить нельзя: `collect_person_detail` начинается с
    `collect_learning_rows(...)[0]`, и на исключённом профиле это IndexError —
    500 вместо «покажите историю точки». Спросили про конкретную карточку —
    отвечаем про неё, какого бы она ни была вида.
    """
    if profile_ids is None:
        return and_(
            EmployeeProfile.status == status,
            EmployeeProfile.account_kind == "person",
        )
    return EmployeeProfile.id.in_(profile_ids or [_EMPTY])


def profiles_stmt(
    profile_ids: list[UUID] | None,
    *,
    status: str = "active",
    q: str | None = None,
    store_id: UUID | None = None,
    position_id: UUID | None = None,
    limit: int = ROWS_HARD_CAP,
):
    """Люди в скоупе с должностью и магазином.

    Тай-брейкер по `id` в ORDER BY обязателен — как в `list_employees`: без
    него порядок между одинаковыми ФИО не стабилен.
    """
    stmt = (
        select(EmployeeProfile, Position.name, Store.name)
        .outerjoin(Position, Position.id == EmployeeProfile.position_id)
        .outerjoin(Store, Store.id == EmployeeProfile.store_id)
        .where(profiles_filter(profile_ids, status), EmployeeProfile.status == status)
    )
    cond = match_condition(EmployeeProfile.full_name, EmployeeProfile.email, q or "")
    if cond is not None:
        stmt = stmt.where(cond)
    if store_id is not None:
        stmt = stmt.where(EmployeeProfile.store_id == store_id)
    if position_id is not None:
        stmt = stmt.where(EmployeeProfile.position_id == position_id)
    return stmt.order_by(EmployeeProfile.full_name, EmployeeProfile.id).limit(limit)


def published_courses_stmt():
    return select(
        Course.id, Course.title, Course.course_type, Course.status, Course.audience_id
    ).where(Course.status == "published")


def audience_membership_stmt(profile_ids: list[UUID], audience_ids: list[UUID]):
    return select(AudienceMember.audience_id, AudienceMember.profile_id).where(
        AudienceMember.audience_id.in_(audience_ids or [_EMPTY]),
        AudienceMember.profile_id.in_(profile_ids or [_EMPTY]),
    )


def assignments_stmt(profile_ids: list[UUID]):
    """Явные назначения — только на опубликованные курсы."""
    return (
        select(
            CourseAssignment.profile_id,
            CourseAssignment.course_id,
            CourseAssignment.due_at,
        )
        .join(Course, Course.id == CourseAssignment.course_id)
        .where(
            CourseAssignment.profile_id.in_(profile_ids or [_EMPTY]),
            Course.status == "published",
        )
    )


def progress_rows_stmt(profile_ids: list[UUID]):
    """Прогресс ПОСТРОЧНО и только по опубликованным курсам.

    JOIN на `courses` — это и есть починка дефекта: без него в счётчики
    попадали архивные и черновые курсы. Строки, а не агрегат: из них же
    считается разбивка по обязательным, второй проход по БД не нужен.
    """
    return (
        select(
            CourseProgress.profile_id,
            CourseProgress.course_id,
            CourseProgress.lessons_completed,
            CourseProgress.lessons_total,
            CourseProgress.started_at,
            CourseProgress.completed_at,
        )
        .join(Course, Course.id == CourseProgress.course_id)
        .where(
            CourseProgress.profile_id.in_(profile_ids or [_EMPTY]),
            Course.status == "published",
        )
    )


def quizzes_passed_stmt(profile_ids: list[UUID]):
    """DISTINCT по тесту — пересдачи не считаются второй раз."""
    return (
        select(QuizAttempt.profile_id, func.count(func.distinct(QuizAttempt.quiz_id)))
        .where(
            QuizAttempt.profile_id.in_(profile_ids or [_EMPTY]),
            QuizAttempt.passed.is_(True),
        )
        .group_by(QuizAttempt.profile_id)
    )


def certificates_count_stmt(profile_ids: list[UUID]):
    return (
        select(Certificate.profile_id, func.count())
        .where(Certificate.profile_id.in_(profile_ids or [_EMPTY]))
        .group_by(Certificate.profile_id)
    )


def points_stmt(profile_ids: list[UUID]):
    return (
        select(ActivityEvent.profile_id, func.sum(ActivityEvent.points))
        .where(ActivityEvent.profile_id.in_(profile_ids or [_EMPTY]))
        .group_by(ActivityEvent.profile_id)
    )


def lesson_counts_stmt(course_ids: list[UUID]):
    """Живое число опубликованных уроков курса.

    `course_progress.lessons_total` — денормализация, которую переписывает
    только завершение урока: публикация нового урока старые строки не трогает,
    поэтому снапшот протухает и бывает `lessons_completed > lessons_total`.
    Каталог сотрудника (`courses.py`) показывает живой счётчик — панель
    руководителя обязана показывать тот же.
    """
    return (
        select(CourseLesson.course_id, func.count())
        .where(
            CourseLesson.course_id.in_(course_ids or [_EMPTY]),
            CourseLesson.status == "published",
        )
        .group_by(CourseLesson.course_id)
    )


# ─── Сборщики ────────────────────────────────────────────────────────────────


async def _auth_states(
    db: AsyncSession, profiles: list[EmployeeProfile]
) -> dict[UUID, str]:
    """Статус учётки тем же словарём, что на экране «Сотрудники».

    Импорт отложенный (приём `services/assistant/*`): функция живёт в ручке
    сотрудников, а дублировать её нельзя — до первого staff-sync утверждать
    «без учётки» запрещено, и два экрана про одного человека обязаны говорить
    одно и то же.
    """
    from app.api.employees import auth_state_for, staff_snapshot_fresh
    from app.config import get_settings

    synced_at = (
        await db.execute(select(func.max(ShadowUser.staff_synced_at)))
    ).scalar_one_or_none()
    staff_synced = staff_snapshot_fresh(
        synced_at,
        now=datetime.now(UTC),
        interval_sec=get_settings().staff_sync_interval_sec,
    )
    employee_ids = [p.employee_id for p in profiles if p.employee_id is not None]
    shadows: dict[UUID, tuple[bool, bool | None]] = {}
    if employee_ids:
        for eid, deleted_at, auth_active in await db.execute(
            select(
                ShadowUser.employee_id, ShadowUser.deleted_at, ShadowUser.auth_active
            ).where(ShadowUser.employee_id.in_(employee_ids))
        ):
            shadows[eid] = (deleted_at is not None, auth_active)
    out: dict[UUID, str] = {}
    for p in profiles:
        shadow_deleted, auth_active = (
            shadows.get(p.employee_id, (False, None)) if p.employee_id else (False, None)
        )
        out[p.id] = auth_state_for(
            employee_id=p.employee_id,
            last_activity_at=p.last_activity_at,
            shadow_deleted=shadow_deleted,
            auth_active=auth_active,
            staff_synced=staff_synced,
        )
    return out


async def collect_learning_rows(
    db: AsyncSession,
    profile_ids: list[UUID] | None,
    *,
    status: str = "active",
    q: str | None = None,
    store_id: UUID | None = None,
    position_id: UUID | None = None,
) -> list[LearningRow]:
    """Строки прогресса по людям. Одна точка правды для экрана, панели и CSV."""
    profiles = (
        await db.execute(
            profiles_stmt(
                profile_ids,
                status=status,
                q=q,
                store_id=store_id,
                position_id=position_id,
            )
        )
    ).all()
    if not profiles:
        return []
    ids = [p.id for p, _, _ in profiles]

    courses = [
        CourseRef(id=cid, title=title, course_type=ctype, status=cstatus, audience_id=aid)
        for cid, title, ctype, cstatus, aid in await db.execute(published_courses_stmt())
    ]
    audience_ids = [c.audience_id for c in courses if c.audience_id is not None]

    members: dict[UUID, set[UUID]] = {}
    if audience_ids:
        for aud_id, pid in await db.execute(
            audience_membership_stmt(ids, audience_ids)
        ):
            members.setdefault(pid, set()).add(aud_id)

    assigned: dict[UUID, set[UUID]] = {}
    for pid, course_id, _due in await db.execute(assignments_stmt(ids)):
        assigned.setdefault(pid, set()).add(course_id)

    progress: dict[UUID, dict[UUID, ProgressRef]] = {}
    for pid, course_id, lc, lt, started, completed in await db.execute(
        progress_rows_stmt(ids)
    ):
        progress.setdefault(pid, {})[course_id] = ProgressRef(
            course_id=course_id,
            lessons_completed=lc,
            lessons_total=lt,
            started_at=started,
            completed_at=completed,
        )

    quiz_map = dict((await db.execute(quizzes_passed_stmt(ids))).all())
    cert_map = dict((await db.execute(certificates_count_stmt(ids))).all())
    points_map = {
        pid: float(pts or 0)
        for pid, pts in (await db.execute(points_stmt(ids))).all()
    }
    states = await _auth_states(db, [p for p, _, _ in profiles])

    rows: list[LearningRow] = []
    for profile, position_name, store_name in profiles:
        mine = progress.get(profile.id, {})
        member_auds = members.get(profile.id, set())
        assigned_ids = assigned.get(profile.id, set())
        mandatory = mandatory_course_ids(courses, member_auds, assigned_ids)
        available = enrolled_course_ids(
            courses, member_auds, assigned_ids, set(mine.keys())
        )
        rows.append(
            LearningRow(
                profile_id=profile.id,
                full_name=profile.full_name,
                email=profile.email,
                position_id=profile.position_id,
                position_name=position_name,
                store_id=profile.store_id,
                store_name=store_name,
                has_account=profile.employee_id is not None,
                auth_state=states.get(profile.id, "not_linked"),
                mandatory_total=len(mandatory),
                mandatory_done=sum(
                    1
                    for cid in mandatory
                    if course_status(mine.get(cid)) == "completed"
                ),
                courses_available=len(available),
                courses_started=len(mine),
                courses_completed=sum(
                    1 for p in mine.values() if p.completed_at is not None
                ),
                quizzes_passed=quiz_map.get(profile.id, 0),
                certificates=cert_map.get(profile.id, 0),
                points=points_map.get(profile.id, 0.0),
                last_activity_at=profile.last_activity_at,
            )
        )
    return rows


@dataclass(slots=True)
class PersonCourse:
    course_id: UUID
    title: str
    course_type: str
    course_status: str
    required: bool
    source: str  # audience | assignment | progress_only
    status: str
    lessons_total: int
    lessons_completed: int
    started_at: datetime | None
    completed_at: datetime | None
    due_at: datetime | None
    certificate_serial: str | None


@dataclass(slots=True)
class PersonAttempt:
    attempt_id: UUID
    quiz_title: str
    attempt_no: int
    finished_at: datetime | None
    score_pct: int | None
    state: str


@dataclass(slots=True)
class PersonDetail:
    row: LearningRow
    courses: list[PersonCourse]
    attempts: list[PersonAttempt]


async def collect_person_detail(
    db: AsyncSession, profile: EmployeeProfile
) -> PersonDetail:
    """Разбор по одному человеку.

    Собирается СВОИМИ запросами, а НЕ вызовом `courses.list_courses`: та
    резолвит профиль из `principal` и вернула бы курсы смотрящего. Подпись
    похожа, тип совпадает, данные чужие — самая дорогая ошибка в этом месте.
    """
    row = (await collect_learning_rows(db, [profile.id], status=profile.status))[0]

    courses = [
        CourseRef(id=cid, title=title, course_type=ctype, status=cstatus, audience_id=aid)
        for cid, title, ctype, cstatus, aid in await db.execute(published_courses_stmt())
    ]
    by_id = {c.id: c for c in courses}
    audience_ids = [c.audience_id for c in courses if c.audience_id is not None]
    member_auds: set[UUID] = set()
    if audience_ids:
        member_auds = {
            aud
            for aud, _ in await db.execute(
                audience_membership_stmt([profile.id], audience_ids)
            )
        }
    due_by_course: dict[UUID, datetime | None] = {}
    assigned_ids: set[UUID] = set()
    for _pid, course_id, due in await db.execute(assignments_stmt([profile.id])):
        assigned_ids.add(course_id)
        due_by_course[course_id] = due

    # Прогресс БЕЗ фильтра по статусу курса: архивные и черновые курсы с
    # прогрессом надо показать, иначе «начато 5» в шапке не сойдётся с четырьмя
    # строками в списке.
    all_progress: dict[UUID, ProgressRef] = {}
    extra_titles: dict[UUID, tuple[str, str, str]] = {}
    for cid, title, ctype, cstatus, lc, lt, started, completed in await db.execute(
        select(
            CourseProgress.course_id,
            Course.title,
            Course.course_type,
            Course.status,
            CourseProgress.lessons_completed,
            CourseProgress.lessons_total,
            CourseProgress.started_at,
            CourseProgress.completed_at,
        )
        .join(Course, Course.id == CourseProgress.course_id)
        .where(CourseProgress.profile_id == profile.id)
    ):
        all_progress[cid] = ProgressRef(
            course_id=cid,
            lessons_completed=lc,
            lessons_total=lt,
            started_at=started,
            completed_at=completed,
        )
        extra_titles[cid] = (title, ctype, cstatus)

    mandatory = mandatory_course_ids(courses, member_auds, assigned_ids)
    available = enrolled_course_ids(
        courses, member_auds, assigned_ids, set(all_progress.keys())
    )
    shown = available | set(all_progress.keys())

    lesson_totals = dict(
        (await db.execute(lesson_counts_stmt(list(shown)))).all()
    )
    certs = dict(
        (
            await db.execute(
                select(Certificate.course_id, Certificate.serial).where(
                    Certificate.profile_id == profile.id
                )
            )
        ).all()
    )

    person_courses: list[PersonCourse] = []
    for cid in shown:
        ref = by_id.get(cid)
        title, ctype, cstatus = (
            (ref.title, ref.course_type, ref.status)
            if ref is not None
            else extra_titles.get(cid, ("Курс снят", "info", "archived"))
        )
        prog = all_progress.get(cid)
        live_total = lesson_totals.get(cid, prog.lessons_total if prog else 0)
        person_courses.append(
            PersonCourse(
                course_id=cid,
                title=title,
                course_type=ctype,
                course_status=cstatus,
                required=cid in mandatory,
                source=(
                    "assignment"
                    if cid in assigned_ids
                    else ("audience" if cid in available else "progress_only")
                ),
                status=course_status(prog),
                lessons_total=live_total,
                # Кламп: снапшот протухает, и «9 из 8» уводит полосу за 100%.
                lessons_completed=min(prog.lessons_completed if prog else 0, live_total),
                started_at=prog.started_at if prog else None,
                completed_at=prog.completed_at if prog else None,
                due_at=due_by_course.get(cid),
                certificate_serial=certs.get(cid),
            )
        )
    person_courses.sort(key=lambda c: (not c.required, c.status != "in_progress", c.title))

    attempts = [
        PersonAttempt(
            attempt_id=aid,
            quiz_title=title or "Тест",
            attempt_no=no,
            finished_at=finished,
            score_pct=score,
            state=attempt_state(
                finished_at=finished,
                needs_review=needs_review,
                reviewed_at=reviewed_at,
                passed=passed,
            ),
        )
        for aid, title, no, finished, score, passed, needs_review, reviewed_at in (
            await db.execute(
                select(
                    QuizAttempt.id,
                    Quiz.title,
                    QuizAttempt.attempt_no,
                    QuizAttempt.finished_at,
                    QuizAttempt.score_pct,
                    QuizAttempt.passed,
                    QuizAttempt.needs_review,
                    QuizAttempt.reviewed_at,
                )
                .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                .where(QuizAttempt.profile_id == profile.id)
                .order_by(QuizAttempt.started_at.desc())
                .limit(DETAIL_ATTEMPTS)
            )
        )
    ]
    return PersonDetail(row=row, courses=person_courses, attempts=attempts)
