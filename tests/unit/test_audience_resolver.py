"""Юнит-тесты чистого ядра audience-резолвера (Ф0 LMS).

Закрывают находки adversarial-ревью плана:
- пустая include-строка НЕ матчит никого (fail-closed) и запрещена валидацией;
- «только exclude-строки» = все активные минус исключённые;
- ТУ матчится на store-правила закреплённых магазинов (+их группы);
- владелец франчайзи матчится на магазины своего франчайзи;
- франчайзи рядового сотрудника выводится из магазина, не из профиля;
- department-правило родителя матчит сотрудников под-отделов.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.audience_resolver import (
    EmployeeAttrs,
    RuleSpec,
    audience_matches,
    build_attrs,
    rule_matches,
    validate_rules,
)
from app.services.employee_profiles import normalize_email

# --- rule_matches ------------------------------------------------------------


def test_empty_rule_matches_nobody():
    attrs = EmployeeAttrs(profile_id=uuid4(), position_ids=frozenset({uuid4()}))
    assert rule_matches(RuleSpec(mode="include"), attrs) is False


def test_single_dimension_match():
    pos = uuid4()
    attrs = EmployeeAttrs(profile_id=uuid4(), position_ids=frozenset({pos}))
    assert rule_matches(RuleSpec(mode="include", position_ids=frozenset({pos})), attrs)
    assert not rule_matches(RuleSpec(mode="include", position_ids=frozenset({uuid4()})), attrs)


def test_and_across_dimensions():
    """«Продавцы группы магазинов X» — оба измерения обязаны совпасть."""
    pos, group = uuid4(), uuid4()
    rule = RuleSpec(
        mode="include",
        position_ids=frozenset({pos}),
        store_group_ids=frozenset({group}),
    )
    both = EmployeeAttrs(
        profile_id=uuid4(),
        position_ids=frozenset({pos}),
        store_group_ids=frozenset({group}),
    )
    only_position = EmployeeAttrs(profile_id=uuid4(), position_ids=frozenset({pos}))
    assert rule_matches(rule, both)
    assert not rule_matches(rule, only_position)


def test_profile_ids_dimension():
    me = uuid4()
    attrs = EmployeeAttrs(profile_id=me)
    assert rule_matches(RuleSpec(mode="include", profile_ids=frozenset({me})), attrs)
    assert not rule_matches(RuleSpec(mode="include", profile_ids=frozenset({uuid4()})), attrs)


# --- audience_matches --------------------------------------------------------


def test_no_rules_means_everyone():
    attrs = EmployeeAttrs(profile_id=uuid4())
    assert audience_matches(False, [], attrs)
    assert audience_matches(True, [], attrs)


def test_include_rows_are_or():
    pos_a, pos_b = uuid4(), uuid4()
    rules = [
        RuleSpec(mode="include", position_ids=frozenset({pos_a})),
        RuleSpec(mode="include", position_ids=frozenset({pos_b})),
    ]
    a = EmployeeAttrs(profile_id=uuid4(), position_ids=frozenset({pos_a}))
    c = EmployeeAttrs(profile_id=uuid4(), position_ids=frozenset({uuid4()}))
    assert audience_matches(False, rules, a)
    assert not audience_matches(False, rules, c)


def test_exclude_subtracts_from_include():
    """«Продавцам группы X, но не стажёрам» (ТЗ §18)."""
    pos, group, interns = uuid4(), uuid4(), uuid4()
    rules = [
        RuleSpec(
            mode="include",
            position_ids=frozenset({pos}),
            store_group_ids=frozenset({group}),
        ),
        RuleSpec(mode="exclude", user_group_ids=frozenset({interns})),
    ]
    seller = EmployeeAttrs(
        profile_id=uuid4(),
        position_ids=frozenset({pos}),
        store_group_ids=frozenset({group}),
    )
    intern_seller = EmployeeAttrs(
        profile_id=uuid4(),
        position_ids=frozenset({pos}),
        store_group_ids=frozenset({group}),
        user_group_ids=frozenset({interns}),
    )
    assert audience_matches(False, rules, seller)
    assert not audience_matches(False, rules, intern_seller)


def test_exclude_only_means_everyone_minus():
    """Нет include-строк → база «все активные», exclude вычитается."""
    interns = uuid4()
    rules = [RuleSpec(mode="exclude", user_group_ids=frozenset({interns}))]
    regular = EmployeeAttrs(profile_id=uuid4())
    intern = EmployeeAttrs(profile_id=uuid4(), user_group_ids=frozenset({interns}))
    assert audience_matches(False, rules, regular)
    assert not audience_matches(False, rules, intern)


def test_exclude_applies_even_with_is_all():
    vip = uuid4()
    rules = [RuleSpec(mode="exclude", profile_ids=frozenset({vip}))]
    assert not audience_matches(True, rules, EmployeeAttrs(profile_id=vip))
    assert audience_matches(True, rules, EmployeeAttrs(profile_id=uuid4()))


# --- validate_rules ----------------------------------------------------------


def test_empty_include_row_is_rejected():
    with pytest.raises(ValueError, match="хотя бы одно условие"):
        validate_rules([RuleSpec(mode="include")])


def test_exclude_only_rules_are_valid():
    validate_rules([RuleSpec(mode="exclude", user_group_ids=frozenset({uuid4()}))])


def test_bad_mode_is_rejected():
    with pytest.raises(ValueError, match="mode"):
        validate_rules([RuleSpec(mode="both", position_ids=frozenset({uuid4()}))])


# --- build_attrs: расширение атрибутов ТУ/франчайзи (ТЗ §2.1) ---------------


def _base_maps() -> dict:
    return {
        "franchisee_to_stores": {},
        "store_to_franchisee": {},
        "position_to_groups": {},
        "store_to_groups": {},
        "franchisee_to_groups": {},
        "department_parents": {},
        "user_group_ids": set(),
        "tu_store_ids": set(),
    }


def test_tu_gets_assigned_stores_and_their_groups():
    store_a, store_b, group = uuid4(), uuid4(), uuid4()
    maps = _base_maps() | {
        "tu_store_ids": {store_a, store_b},
        "store_to_groups": {store_a: {group}},
    }
    attrs = build_attrs(
        profile_id=uuid4(),
        org_role="tu",
        position_id=None,
        store_id=None,
        department_id=None,
        profile_franchisee_id=None,
        **maps,
    )
    assert attrs.store_ids == frozenset({store_a, store_b})
    assert attrs.store_group_ids == frozenset({group})
    # ТУ не наследует франчайзи закреплённых магазинов.
    assert attrs.franchisee_ids == frozenset()


def test_franchisee_owner_gets_his_stores():
    franchisee, store_a, store_b = uuid4(), uuid4(), uuid4()
    maps = _base_maps() | {
        "franchisee_to_stores": {franchisee: {store_a, store_b}},
    }
    attrs = build_attrs(
        profile_id=uuid4(),
        org_role="franchisee_owner",
        position_id=None,
        store_id=None,
        department_id=None,
        profile_franchisee_id=franchisee,
        **maps,
    )
    assert attrs.store_ids == frozenset({store_a, store_b})
    assert attrs.franchisee_ids == frozenset({franchisee})


def test_employee_franchisee_derived_from_store():
    """Франчайзи рядового сотрудника — из store.franchisee_id, не из профиля."""
    franchisee, store = uuid4(), uuid4()
    maps = _base_maps() | {"store_to_franchisee": {store: franchisee}}
    attrs = build_attrs(
        profile_id=uuid4(),
        org_role="employee",
        position_id=None,
        store_id=store,
        department_id=None,
        profile_franchisee_id=None,
        **maps,
    )
    assert attrs.franchisee_ids == frozenset({franchisee})


def test_department_rule_matches_descendants():
    """Материал «отделу Маркетинг» виден сотруднику под-отдела Digital."""
    marketing, digital = uuid4(), uuid4()
    maps = _base_maps() | {"department_parents": {digital: marketing, marketing: None}}
    attrs = build_attrs(
        profile_id=uuid4(),
        org_role="office",
        position_id=None,
        store_id=None,
        department_id=digital,
        profile_franchisee_id=None,
        **maps,
    )
    assert attrs.department_ids == frozenset({digital, marketing})
    assert rule_matches(
        RuleSpec(mode="include", department_ids=frozenset({marketing})), attrs
    )


def test_department_cycle_does_not_hang():
    a, b = uuid4(), uuid4()
    maps = _base_maps() | {"department_parents": {a: b, b: a}}
    attrs = build_attrs(
        profile_id=uuid4(),
        org_role="office",
        position_id=None,
        store_id=None,
        department_id=a,
        profile_franchisee_id=None,
        **maps,
    )
    assert attrs.department_ids == frozenset({a, b})


# --- normalize_email ---------------------------------------------------------


def test_normalize_email():
    assert normalize_email("  Ivanov@Uppetit.RU ") == "ivanov@uppetit.ru"
