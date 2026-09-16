"""Арифметика «Прогресса сотрудников» — чистые правила без БД.

Почему юнит, а не интеграция: «обязательных X из N» — главное число экрана, а
интеграционные тесты в CI не бегут (`-m "not integration"`). Именно поэтому
знаменатель вынесен в чистую функцию, а не спрятан в коррелированный `select`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.services.learning_progress import (
    CourseRef,
    LearningRow,
    ProgressRef,
    attempt_state,
    course_status,
    enrolled_course_ids,
    mandatory_course_ids,
    pct,
    summarize,
)

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)

AUD_TU = uuid.uuid4()
MAND_ALL = uuid.uuid4()
MAND_AUD = uuid.uuid4()
MAND_DRAFT = uuid.uuid4()
MAND_ARCHIVED = uuid.uuid4()
RECOMMENDED = uuid.uuid4()
CAREER = uuid.uuid4()


def _catalog() -> list[CourseRef]:
    return [
        CourseRef(MAND_ALL, "Добро пожаловать", "mandatory", "published", None),
        CourseRef(MAND_AUD, "Территориальный управляющий", "mandatory", "published", AUD_TU),
        CourseRef(MAND_DRAFT, "Черновик", "mandatory", "draft", None),
        CourseRef(MAND_ARCHIVED, "Снят", "mandatory", "archived", None),
        CourseRef(RECOMMENDED, "Техника продаж", "recommended", "published", None),
        CourseRef(CAREER, "Наставник", "career", "published", None),
    ]


def _progress(course_id: uuid.UUID, *, done: bool) -> ProgressRef:
    return ProgressRef(
        course_id=course_id,
        lessons_completed=9 if done else 3,
        lessons_total=9,
        started_at=NOW,
        completed_at=NOW if done else None,
    )


# ─── Знаменатель ─────────────────────────────────────────────────────────────


def test_course_for_everyone_counts_for_everyone():
    assert mandatory_course_ids(_catalog(), set(), set()) == {MAND_ALL}


def test_audience_course_counts_only_for_members():
    assert MAND_AUD in mandatory_course_ids(_catalog(), {AUD_TU}, set())
    assert MAND_AUD not in mandatory_course_ids(_catalog(), set(), set())


def test_assignment_adds_course_to_a_non_member():
    """Назначенный курс сотрудник видит у себя даже вне аудитории."""
    without = mandatory_course_ids(_catalog(), set(), set())
    with_assignment = mandatory_course_ids(_catalog(), set(), {MAND_AUD})
    assert len(with_assignment) == len(without) + 1


def test_non_mandatory_types_never_count():
    ids = mandatory_course_ids(_catalog(), {AUD_TU}, {RECOMMENDED, CAREER})
    assert RECOMMENDED not in ids
    assert CAREER not in ids


def test_draft_and_archived_mandatory_never_count():
    ids = mandatory_course_ids(_catalog(), set(), {MAND_DRAFT, MAND_ARCHIVED})
    assert MAND_DRAFT not in ids
    assert MAND_ARCHIVED not in ids


# ─── Что человек видит у себя ────────────────────────────────────────────────


def test_enrolled_mirrors_my_learning():
    """`назначен ИЛИ есть прогресс ИЛИ обязательный` по видимым + назначенным."""
    ids = enrolled_course_ids(_catalog(), set(), set(), set())
    assert ids == {MAND_ALL}  # обязательный всем — единственный без условий

    with_progress = enrolled_course_ids(_catalog(), set(), set(), {RECOMMENDED})
    assert RECOMMENDED in with_progress


def test_progress_on_invisible_unassigned_course_does_not_enroll():
    """Аудиторный курс без членства и без назначения не «мой», даже с прогрессом."""
    ids = enrolled_course_ids(_catalog(), set(), set(), {MAND_AUD})
    assert MAND_AUD not in ids


# ─── Статус курса ────────────────────────────────────────────────────────────


def test_course_status_three_branches():
    assert course_status(None) == "not_started"
    assert course_status(_progress(MAND_ALL, done=False)) == "in_progress"
    assert course_status(_progress(MAND_ALL, done=True)) == "completed"


def test_completed_at_wins_over_lesson_mismatch():
    """`completed_at` иммутабелен: курс, закрытый до добавления уроков, завершён."""
    stale = ProgressRef(MAND_ALL, 5, 8, NOW, NOW)
    assert course_status(stale) == "completed"


# ─── Проценты ────────────────────────────────────────────────────────────────


def test_pct_values():
    assert pct(0, 6) == 0
    assert pct(5, 6) == 83
    assert pct(6, 6) == 100


def test_pct_of_nothing_is_none_not_zero():
    """«Нечего проходить» и «ничего не прошёл» — разные факты."""
    assert pct(0, 0) is None


def test_pct_clamps_stale_snapshot():
    """Снапшот протухает и даёт «9 из 8» — за 100% полоса уезжать не должна."""
    assert pct(9, 8) == 100


# ─── Попытки тестов ──────────────────────────────────────────────────────────


def test_attempt_on_manual_review_is_not_failed():
    """У попытки на проверке `passed` ещё None — без ветки она была бы «провал»."""
    assert (
        attempt_state(
            finished_at=NOW, needs_review=True, reviewed_at=None, passed=None
        )
        == "pending_review"
    )


def test_attempt_states():
    assert (
        attempt_state(
            finished_at=None, needs_review=False, reviewed_at=None, passed=None
        )
        == "in_progress"
    )
    assert (
        attempt_state(
            finished_at=NOW, needs_review=False, reviewed_at=None, passed=True
        )
        == "passed"
    )
    assert (
        attempt_state(
            finished_at=NOW, needs_review=False, reviewed_at=None, passed=False
        )
        == "failed"
    )
    assert (
        attempt_state(finished_at=NOW, needs_review=True, reviewed_at=NOW, passed=True)
        == "passed"
    )


# ─── Сводка ──────────────────────────────────────────────────────────────────


def _row(
    *,
    total: int,
    done: int,
    has_account: bool = True,
    last_activity: datetime | None = NOW,
) -> LearningRow:
    return LearningRow(
        profile_id=uuid.uuid4(),
        full_name="Тест",
        email="t@example.com",
        position_id=None,
        position_name=None,
        store_id=None,
        store_name=None,
        has_account=has_account,
        auth_state="active" if has_account else "no_account",
        mandatory_total=total,
        mandatory_done=done,
        courses_available=total,
        courses_started=done,
        courses_completed=done,
        quizzes_passed=0,
        certificates=0,
        points=0.0,
        last_activity_at=last_activity,
    )


def test_summary_counts_buckets():
    rows = [
        _row(total=6, done=6),
        _row(total=6, done=3),
        _row(total=6, done=0),
        _row(total=6, done=0, has_account=False, last_activity=None),
    ]
    s = summarize(rows)
    assert s.people == 4
    assert s.completed_all == 1
    assert s.completed_none == 2
    assert s.without_account == 1
    assert s.never_active == 1


def test_people_with_nothing_assigned_are_not_counted_as_completed():
    """`0 из 0` не «завершил всё» — иначе KPI растёт на ровном месте."""
    s = summarize([_row(total=0, done=0)])
    assert s.completed_all == 0
    assert s.completed_none == 0
    assert s.mandatory_pct is None


def test_summary_pct_uses_totals_not_average_of_people():
    """Доля считается от суммы, а не как среднее долей.

    5/8 = 62,5 → 62: `round` в Python округляет половину к чётному, и это то
    же поведение, что у остальной learn-аналитики (`avg_quiz_score`). Разница в
    один процент на ровно половинном значении цены не имеет, а вторая манера
    округления в одном продукте — имеет.
    """
    rows = [_row(total=6, done=3), _row(total=2, done=2)]
    s = summarize(rows)
    assert s.mandatory_total == 8
    assert s.mandatory_done == 5
    assert s.mandatory_pct == 62


def test_summary_of_empty_scope():
    """Пустой скоуп — рабочее состояние ТУ без закреплённых магазинов."""
    s = summarize([])
    assert s.people == 0
    assert s.mandatory_pct is None
