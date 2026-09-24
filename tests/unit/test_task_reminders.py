"""Личные напоминания (0062) — чистые правила `services/task_reminders.py`.

CI гоняет только юниты, поэтому здесь каждое правило, найденное при разборе
плана: offset 0 срабатывает В ТИКЕ (а не засыпает, увидев якорь «в прошлом»),
правило переживает срабатывание и взводится при переносе срока, `due_day`
не превращается в «к сроку», промежуточные сроки старых бандлов не стреляют.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services import task_reminders as tr
from app.services.taskdates import due_noon_utc

MSK = ZoneInfo("Europe/Moscow")


def _msk(y: int, m: int, d: int, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=MSK).astimezone(UTC)


BASE = tr.TaskFacts(
    due_at=_msk(2026, 9, 30, 15),
    due_has_time=True,
    start_at=None,
    start_has_time=False,
    done=False,
    archived=False,
    project_archived=False,
)


def _tick(anchor: str, offset: int, now: datetime, *, facts=BASE, fired=None, stored=None):
    return tr.decide(
        anchor=anchor,
        offset_minutes=offset,
        facts=facts,
        fired_anchor_at=fired,
        stored_fire_at=stored,
        now=now,
        mode="tick",
    )


def _resched(anchor: str, offset: int, now: datetime, *, facts=BASE, fired=None, stored=None):
    return tr.decide(
        anchor=anchor,
        offset_minutes=offset,
        facts=facts,
        fired_anchor_at=fired,
        stored_fire_at=stored,
        now=now,
        mode="reschedule",
    )


# ─── Якоря ──────────────────────────────────────────────────────────────────


def test_due_anchor_is_the_moment_or_morning() -> None:
    assert tr.anchor_moment("due", BASE) == _msk(2026, 9, 30, 15)
    day_only = replace(BASE, due_at=due_noon_utc(date(2026, 9, 30)), due_has_time=False)
    assert tr.anchor_moment("due", day_only) == _msk(2026, 9, 30, 9)


def test_due_day_ignores_time() -> None:
    # «Утром в день срока» не превращается в «к сроку 15:00», когда время
    # дописали позже.
    assert tr.anchor_moment("due_day", BASE) == _msk(2026, 9, 30, 9)


def test_start_anchor_and_missing_dates() -> None:
    started = replace(BASE, start_at=_msk(2026, 9, 29, 10), start_has_time=True)
    assert tr.anchor_moment("start", started) == _msk(2026, 9, 29, 10)
    assert tr.anchor_moment("start", BASE) is None
    assert tr.anchor_moment("at", BASE) is None


# ─── Тик ────────────────────────────────────────────────────────────────────


def test_offset_zero_fires_a_few_seconds_late() -> None:
    # Блокер ревью: тик в 15:00:07 видит якорь 15:00 «в прошлом». Засыпать
    # нельзя — иначе «к сроку»/«к началу» не сработали бы никогда.
    d = _tick("due", 0, _msk(2026, 9, 30, 15, 0, 7), stored=_msk(2026, 9, 30, 15))
    assert d.action == "fire"
    assert d.anchor_at == _msk(2026, 9, 30, 15)


def test_late_tick_within_grace_still_fires() -> None:
    d = _tick("due", 0, _msk(2026, 9, 30, 15, 10), stored=_msk(2026, 9, 30, 15))
    assert d.action == "fire"


def test_anchor_long_past_sleeps() -> None:
    d = _tick("due", 60, _msk(2026, 9, 30, 16), stored=_msk(2026, 9, 30, 14))
    assert (d.action, d.state) == ("sleep", "passed")


def test_intermediate_year_does_not_fire() -> None:
    # Набор года с клавиатуры в старом бандле пишет 1902/0202 — правило спит.
    facts = replace(BASE, due_at=datetime(1902, 9, 30, 9, 29, 43, tzinfo=UTC))
    d = _resched("due", 60, _msk(2026, 9, 29, 10), facts=facts)
    assert (d.action, d.state) == ("sleep", "passed")


def test_fired_rule_sleeps_until_anchor_moves() -> None:
    now = _msk(2026, 9, 30, 14, 30)
    fired = _msk(2026, 9, 30, 15)
    d = _resched("due", 60, now, fired=fired)
    assert (d.action, d.state) == ("sleep", "fired")
    moved = replace(BASE, due_at=_msk(2026, 10, 1, 15))
    d = _resched("due", 60, now, facts=moved, fired=fired)
    assert (d.action, d.fire_at) == ("arm", _msk(2026, 10, 1, 14))


def test_deadline_moved_closer_than_offset_catches_up() -> None:
    now = _msk(2026, 9, 30, 14, 30)
    d = _resched("due", 60, now)  # за час до 15:00 = 14:00 — уже прошло
    assert d.action == "arm"
    assert d.fire_at == now + tr.CATCHUP


def test_tick_rearms_when_deadline_moved_later_without_reschedule() -> None:
    moved = replace(BASE, due_at=_msk(2026, 10, 2, 15))
    d = _tick("due", 60, _msk(2026, 9, 30, 14), facts=moved, stored=_msk(2026, 9, 30, 14))
    assert (d.action, d.fire_at) == ("arm", _msk(2026, 10, 2, 14))


def test_done_archived_and_missing_date_sleep() -> None:
    now = _msk(2026, 9, 30, 10)
    assert _tick("due", 0, now, facts=replace(BASE, done=True)).state == "done"
    assert _tick("due", 0, now, facts=replace(BASE, project_archived=True)).state == "archived"
    no_due = replace(BASE, due_at=None, due_has_time=False)
    d = _tick("due", 0, now, facts=no_due)
    assert (d.action, d.state) == ("sleep", "no_date")


def test_overflow_sleeps_instead_of_crashing() -> None:
    facts = replace(BASE, due_at=datetime(1, 1, 1, tzinfo=UTC), due_has_time=True)
    d = _resched("due", 10080, datetime(1, 1, 3, tzinfo=UTC), facts=facts)
    assert d.action == "sleep"


# ─── Разовые ────────────────────────────────────────────────────────────────


def test_at_fires_once_and_drops_when_stale_or_done() -> None:
    at = _msk(2026, 9, 30, 16, 42)
    assert _tick("at", 0, at + timedelta(seconds=3), stored=at).action == "fire"
    assert _tick("at", 0, at + timedelta(hours=3), stored=at).action == "delete"
    assert _tick("at", 0, at, facts=replace(BASE, done=True), stored=at).action == "delete"
    # Перерасчёт разовые не трогает.
    assert _resched("at", 0, at, stored=at).fire_at == at


# ─── Доступ ─────────────────────────────────────────────────────────────────


def test_may_receive() -> None:
    me, other = uuid.uuid4(), uuid.uuid4()
    common = {"employee_id": me, "deleted": False, "via_admin": False, "involved": False}
    assert tr.may_receive(personal_owner_id=None, is_member=True, **common)
    assert not tr.may_receive(personal_owner_id=None, is_member=False, **common)
    assert tr.may_receive(personal_owner_id=None, is_member=False, **{**common, "via_admin": True})
    # Своё личное — всегда; чужое — только участник-исполнитель/наблюдатель.
    assert tr.may_receive(personal_owner_id=me, is_member=False, **common)
    assert not tr.may_receive(personal_owner_id=other, is_member=True, **common)
    assert tr.may_receive(personal_owner_id=other, is_member=True, **{**common, "involved": True})
    # hub-admin личное не обходит.
    admin = {**common, "via_admin": True}
    assert not tr.may_receive(personal_owner_id=other, is_member=False, **admin)
    gone = {**common, "deleted": True}
    assert not tr.may_receive(personal_owner_id=None, is_member=True, **gone)


# ─── Выдача и текст ─────────────────────────────────────────────────────────


def test_item_state_reports_fired_moment() -> None:
    now = _msk(2026, 9, 30, 14, 30)
    state, fire_at, fired_at = tr.item_state(
        anchor="due", offset_minutes=60, facts=BASE, fired_anchor_at=_msk(2026, 9, 30, 15),
        fire_at=None, now=now,
    )
    assert (state, fire_at, fired_at) == ("fired", None, _msk(2026, 9, 30, 14))
    state, fire_at, _ = tr.item_state(
        anchor="due", offset_minutes=60, facts=BASE, fired_anchor_at=None,
        fire_at=_msk(2026, 9, 30, 14), now=_msk(2026, 9, 30, 10),
    )
    assert (state, fire_at) == ("armed", _msk(2026, 9, 30, 14))


def test_reminder_body() -> None:
    now = _msk(2026, 9, 30, 10)
    body = tr.reminder_body("due", "Сдать отчёт", BASE, now)
    assert body == "«Сдать отчёт» — срок сегодня в 15:00"
    started = replace(BASE, start_at=due_noon_utc(date(2026, 10, 1)), start_has_time=False)
    assert tr.reminder_body("start_day", "Смена", started, now) == "«Смена» — начало завтра"
    no_dates = replace(BASE, due_at=None, due_has_time=False)
    assert tr.reminder_body("at", "Позвонить", no_dates, now) == "«Позвонить»"
