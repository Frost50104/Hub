"""Кадровые данные из auth (16d): план по карточкам — без БД.

Разбор блока `hr`, исходы для карточки (заполнение / изменение / не трогать),
правило точки и ТУ, руководитель, правило K со сверкой имени, предохранитель,
отпечаток и счёт новых обязательных членств.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from app.services.hr_apply import (
    Card,
    OrgMapsView,
    PlanContext,
    StaffRow,
    ValveDecision,
    count_new_mandatory,
    deactivation_min_age,
    fingerprint,
    name_key,
    parse_hr_block,
    parse_staff_row,
    plan_card,
    plan_deactivation,
    same_person_name,
)
from app.services.org_directory_sync import AMBIGUOUS

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _card(**kw) -> Card:
    base = {
        "id": uuid4(),
        "employee_id": uuid4(),
        "email": "a@t.ru",
        "full_name": "Мария Иванова",
        "status": "active",
        "account_kind": "person",
        "archive_reason": None,
        "auth_deactivated_name": None,
        "created_at": NOW - timedelta(days=30),
        "hired_at": None,
        "org_role": "employee",
        "position_id": None,
        "store_id": None,
        "department_id": None,
        "franchisee_id": None,
        "manager_profile_id": None,
        "tu_store_ids": frozenset(),
    }
    base.update(kw)
    return Card(**base)


def _block(**kw):
    raw = {
        "authoritative": True,
        "hired_at": None,
        "org_role": "employee",
        "position_id": None,
        "department_id": None,
        "franchisee_id": None,
        "site_id": None,
        "manager_employee_id": None,
        "assigned_site_ids": [],
    }
    raw.update({k: (str(v) if hasattr(v, "hex") else v) for k, v in kw.items()})
    block = parse_hr_block(raw)
    assert block is not None
    return block


# --- Разбор ------------------------------------------------------------------------


def test_parse_block_keeps_valid_and_marks_bad_fields():
    pos = uuid4()
    block = parse_hr_block(
        {
            "authoritative": True,
            "hired_at": "не дата",
            "org_role": "boss",
            "position_id": str(pos),
            "department_id": "x",
            "assigned_site_ids": [str(pos), "y"],
        }
    )
    assert block is not None
    assert block.values == {"position_id": pos}
    assert set(block.bad) == {"hired_at", "org_role", "department_id", "assigned_site_ids"}
    assert block.assigned_site_ids is None  # битый список — поле не трогаем


def test_parse_block_absent_or_without_flag_is_none():
    assert parse_hr_block(None) is None
    assert parse_hr_block({"org_role": "tu"}) is None  # нет authoritative
    assert parse_hr_block("hr") is None


def test_missing_key_means_untouched_null_means_clear():
    block = parse_hr_block({"authoritative": True, "position_id": None})
    assert block is not None
    assert block.values == {"position_id": None}
    assert block.assigned_site_ids is None


def test_parse_staff_row():
    eid = uuid4()
    row = parse_staff_row(
        {
            "kind": "employee",
            "employee_id": str(eid),
            "email": " A@T.ru ",
            "full_name": " Мария ",
            "is_active": "yes",
            "hr": {"org_role": "tu"},
        }
    )
    assert row is not None
    assert (row.email, row.full_name, row.is_active) == ("a@t.ru", "Мария", None)
    assert row.hr is None and row.hr_bad is True
    assert parse_staff_row({"kind": "invitation", "email": "x@t.ru"}) is None
    assert parse_staff_row({"employee_id": "не uuid", "email": "x@t.ru"}) is None


# --- План карточки --------------------------------------------------------------------


def _ctx(**kw) -> PlanContext:
    base = {
        "site_map": {},
        "positions": set(),
        "departments": set(),
        "franchisees": set(),
        "manager_by_employee": {},
    }
    base.update(kw)
    return PlanContext(**base)


def test_fill_empty_card_is_not_counted_change():
    pos, store, site = uuid4(), uuid4(), uuid4()
    card = _card()
    plan = plan_card(
        card,
        _block(position_id=pos, site_id=site, hired_at="2024-03-01"),
        _ctx(site_map={site: store}, positions={pos}),
        linked_this_run=False,
    )
    assert plan.outcome == "fill"
    assert plan.changes == {
        "position_id": (None, pos),
        "store_id": (None, store),
        "hired_at": (None, date(2024, 3, 1)),
    }


def test_change_on_filled_card_and_none_when_equal():
    old, new = uuid4(), uuid4()
    card = _card(position_id=old)
    ctx = _ctx(positions={old, new})
    plan = plan_card(card, _block(position_id=new), ctx, linked_this_run=False)
    assert plan.outcome == "change" and plan.changes == {"position_id": (old, new)}
    assert plan_card(card, _block(position_id=old), ctx, linked_this_run=False).outcome == "none"


def test_just_linked_card_with_empty_block_is_untouched():
    """Требование 5: карточку привязал этот прогон, а блок пуст целиком —
    не затираем кадровые поля, заведённые в Hub."""
    card = _card(position_id=uuid4())
    plan = plan_card(card, _block(), _ctx(), linked_this_run=True)
    assert plan.outcome == "skip_linked_empty" and not plan.touches
    # Тот же блок у карточки, привязанной раньше, — это честная очистка.
    plan = plan_card(card, _block(), _ctx(positions=set()), linked_this_run=False)
    assert plan.changes == {"position_id": (card.position_id, None)}


def test_unknown_refs_and_sites_skip_only_that_field():
    known, ghost, site_ok, site_dup, site_none, store = (uuid4() for _ in range(6))
    card = _card(position_id=known)
    plan = plan_card(
        card,
        _block(
            position_id=ghost,
            department_id=None,
            site_id=site_dup,
            org_role="office",
            manager_employee_id=uuid4(),
        ),
        _ctx(site_map={site_ok: store, site_dup: AMBIGUOUS}, positions={known}),
        linked_this_run=False,
    )
    assert plan.changes == {"org_role": ("employee", "office")}
    assert sorted(plan.skips) == ["ambiguous_site", "unknown_manager", "unknown_ref"]
    plan = plan_card(card, _block(site_id=site_none), _ctx(), linked_this_run=False)
    assert plan.skips == ["unknown_site"] and "store_id" not in plan.changes


def test_tu_translated_whole_or_untouched():
    s1, s2, st1, st2 = uuid4(), uuid4(), uuid4(), uuid4()
    card = _card(org_role="tu", tu_store_ids=frozenset({st1}))
    ctx = _ctx(site_map={s1: st1, s2: st2})
    plan = plan_card(card, _block(org_role="tu", assigned_site_ids=[str(s1), str(s2)]), ctx,
                     linked_this_run=False)
    assert plan.tu == (frozenset({st1}), frozenset({st1, st2}))
    # Одна точка не переводится — набор не трогаем целиком (ANSWER §3.5).
    plan = plan_card(card, _block(org_role="tu", assigned_site_ids=[str(s1), str(uuid4())]), ctx,
                     linked_this_run=False)
    assert plan.tu is None and plan.skips == ["tu_partial"]


def test_manager_resolves_to_card_and_not_to_self():
    boss_eid, boss_card = uuid4(), uuid4()
    card = _card()
    ctx = _ctx(manager_by_employee={boss_eid: boss_card, card.employee_id: card.id})
    plan = plan_card(card, _block(manager_employee_id=boss_eid), ctx, linked_this_run=False)
    assert plan.changes == {"manager_profile_id": (None, boss_card)}
    plan = plan_card(card, _block(manager_employee_id=card.employee_id), ctx,
                     linked_this_run=False)
    assert plan.skips == ["self_manager"] and not plan.changes


# --- Правило K --------------------------------------------------------------------------


def _row(card: Card, *, active: bool | None, name: str = "Мария Иванова", kind="person"):
    return StaffRow(
        employee_id=card.employee_id,
        email=card.email,
        full_name=name,
        role="member",
        is_active=active,
        raw_kind=kind,
        deleted=False,
        hr=None,
    )


def _k(card: Card, row: StaffRow, *, runs=3, since=NOW - timedelta(hours=1), **kw):
    return plan_deactivation(
        row,
        card,
        inactive_runs=runs,
        inactive_since=since,
        runs_needed=3,
        min_age=deactivation_min_age(3, 900),
        now=NOW,
        **kw,
    )


def test_min_age_is_k_minus_one_intervals_minus_five_minutes():
    assert deactivation_min_age(3, 900) == timedelta(minutes=25)


def test_archive_needs_runs_age_raw_person_and_active_card():
    card = _card()
    row = _row(card, active=False)
    action = _k(card, row)
    assert action is not None and action.action == "archive" and action.name == "Мария Иванова"
    assert _k(card, row, runs=2) is None
    assert _k(card, row, since=NOW - timedelta(minutes=10)) is None  # кнопка/рестарты
    assert _k(card, _row(card, active=False, kind=None)) is None  # сырой вид — не person
    assert _k(_card(account_kind="service"), row) is None
    assert _k(card, _row(card, active=None)) is None  # «не знаю» — не отключение


def test_return_same_name_any_word_order_and_release_on_other_name():
    card = _card(
        status="archived", archive_reason="auth_deactivated", auth_deactivated_name="Мария Иванова"
    )
    back = _k(card, _row(card, active=True, name="иванова мария"))
    assert back is not None and back.action == "return" and back.email == card.email
    other = _k(card, _row(card, active=True, name="Пётр Петров"), release_on_name_mismatch=True)
    assert other is not None and other.action == "release"
    assert other.name == "Мария Иванова"  # имя прежнего человека — архивной карточке


def test_after_auth_fix_mismatch_returns_with_warning():
    card = _card(
        status="archived", archive_reason="auth_deactivated", auth_deactivated_name="Мария Иванова"
    )
    # Умолчание с выката auth 25.09: несовпадение имени — тот же человек.
    action = _k(card, _row(card, active=True, name="Мария Петрова"))
    assert action is not None and action.action == "return" and action.name_mismatch is True


def test_other_archive_reasons_are_not_returned():
    for reason in ("manual", "auto_inactivity", "auth_deleted"):
        card = _card(
            status="archived", archive_reason=reason, auth_deactivated_name="Мария Иванова"
        )
        assert _k(card, _row(card, active=True)) is None


@pytest.mark.parametrize(
    ("left", "right", "same"),
    [
        ("Мария Иванова", "иванова  мария", True),
        ("Пётр Семёнов", "Петр Семенов", True),
        ("Мария Иванова", "Мария Петрова", False),
        (None, "Мария", False),
        ("", "", False),
    ],
)
def test_same_person_name(left, right, same):
    assert same_person_name(left, right) is same
    assert name_key("Ёлка Анна") == "анна елка"


# --- Предохранитель, отпечаток, обязательные членства ------------------------------------------


def test_valve_trips_on_either_threshold():
    assert not ValveDecision(10, 20, 10, 20).tripped
    tripped = ValveDecision(11, 0, 10, 20)
    assert tripped.tripped and tripped.reason() == "карточек 11 > 10"
    assert ValveDecision(0, 21, 10, 20).reason() == "обязательных членств 21 > 20"


def test_fingerprint_is_order_independent_and_sensitive():
    a, b = ["card", "1", [["position_id", None, "x"]], None], ["k", "2", "archive"]
    assert fingerprint([a, b]) == fingerprint([b, a])
    assert fingerprint([a]) != fingerprint([a, b])


def test_count_new_mandatory_skips_done_items():
    aud, other, profile, course, material = (uuid4() for _ in range(5))
    items = {aud: [("course", course), ("material", material)]}
    added = {profile: {aud, other}}
    assert count_new_mandatory(added, items, set()) == 1  # other без обязательного
    done_course = {("course", course, profile)}
    assert count_new_mandatory(added, items, done_course) == 1  # документ не подтверждён
    all_done = done_course | {("material", material, profile)}
    assert count_new_mandatory(added, items, all_done) == 0


def test_maps_with_changes_moves_store_franchisee_and_department_parent():
    s1, s2, f1, f2, d1, d2 = (uuid4() for _ in range(6))
    maps = OrgMapsView(
        franchisee_to_stores={f1: {s1}},
        store_to_franchisee={s1: f1},
        position_to_groups={},
        store_to_groups={},
        franchisee_to_groups={},
        department_parents={d1: None, d2: None},
        user_groups={},
    )
    after = maps.with_changes(
        store_franchisee={s1: None, s2: f2},
        department_parent={d2: d1},
        live_stores={s1, s2},
    )
    assert after.store_to_franchisee == {s2: f2}
    assert after.franchisee_to_stores == {f2: {s2}}
    assert after.department_parents == {d1: None, d2: d1}
    assert maps.store_to_franchisee == {s1: f1}  # исходные карты не мутируются
