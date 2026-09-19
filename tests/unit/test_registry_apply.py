"""Правила применения реестра к магазинам (`registry_apply.plan_apply`).

Интеграционные тесты в CI не бегут, а здесь ровно те решения, которые
стоят денег: создать дубль, заархивировать не то, воскресить архивное.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.services.registry_apply import (
    FieldChange,
    SiteRow,
    StoreRow,
    field_changes,
    iiko_ref,
    norm_name,
    plan_apply,
)

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)


def _site(name="Витебский 101", *, code="В101", iiko="dep-1", archived=False, site_id=None):
    return SiteRow(
        site_id=site_id or uuid4(),
        code=code,
        name=name,
        address="СПб",
        archived_at=NOW if archived else None,
        iiko_ref=iiko,
    )


def _store(name, *, code=None, site_id=None, archived=False, **registry):
    return StoreRow(
        id=uuid4(),
        name=name,
        code=code,
        site_id=site_id,
        archived_at=NOW if archived else None,
        **registry,
    )


def test_live_site_with_iiko_and_no_store_is_created():
    site = _site()
    plan = plan_apply([site], [_store("Другая", code="Д1")])
    assert plan.create == [site] and not plan.archive and not plan.pending


def test_site_without_iiko_ref_waits_for_a_human():
    site = _site("Смоленка 35", code=None, iiko=None)
    plan = plan_apply([site], [])
    assert not plan.create
    assert [(p.site, p.reason) for p in plan.pending] == [(site, "no_iiko_ref")]


def test_stop_rule_by_code_and_by_name_names_the_candidate():
    by_code = _store("Комендантский проспект", code="к17")
    by_name = _store("Витебский проспект, дом 101")
    plan = plan_apply(
        [
            _site("Коменданский пр., 17", code="К17"),
            _site("Витебский проспект дом 101", code="В101"),
        ],
        [by_code, by_name],
    )
    assert not plan.create
    assert {(p.reason, p.candidate_store_id) for p in plan.pending} == {
        ("code_collision", by_code.id),
        ("name_collision", by_name.id),
    }


def test_stop_rule_ignores_archived_stores_but_not_linked_live_names():
    other_site = uuid4()
    archived = _store("Витебский 101", code="В101", archived=True)
    site = _site()
    assert plan_apply([site], [archived]).create == [site], "архивная карточка не мешает"
    # живая карточка с тем же именем, пусть и привязанная к другому объекту, —
    # uq_stores_active_name уронил бы INSERT: ждём человека, кандидата нет
    linked = _store("Витебский 101", code="В102", site_id=other_site)
    plan = plan_apply([site, _site("Чужой", site_id=other_site)], [linked])
    assert not plan.create
    assert [(p.reason, p.candidate_store_id) for p in plan.pending] == [("name_collision", None)]


def test_archived_site_archives_live_store_only_once_and_never_restores():
    site_id = uuid4()
    live = _store("Ветеранов 185", code="В185", site_id=site_id)
    plan = plan_apply([_site("Ветеранов 185", archived=True, site_id=site_id)], [live])
    assert [(st.id, s.site_id) for st, s in plan.archive] == [(live.id, site_id)]
    # уже архивная карточка — повторный прогон пуст
    gone = _store("Ветеранов 185", code="В185", site_id=site_id, archived=True)
    assert not plan_apply([_site("Ветеранов 185", archived=True, site_id=site_id)], [gone]).archive
    # объект снова живой — карточка НЕ воскресает (асимметрия)
    plan = plan_apply([_site("Ветеранов 185", site_id=site_id)], [gone])
    assert not plan.archive and not plan.create and not plan.pending


def test_site_with_any_store_is_never_created_again_even_for_duplicates():
    site_id = uuid4()
    a = _store("Кременчугская 13", site_id=site_id)
    b = _store("Кременчугская 13 к.1", site_id=site_id)
    plan = plan_apply([_site("Кременчугская 13 к.1", site_id=site_id)], [a, b])
    assert not plan.create and not plan.pending and not plan.archive


def test_archived_site_without_store_is_ignored():
    assert plan_apply([_site(archived=True)], []) == plan_apply([], [])


def test_norm_name_and_iiko_ref():
    assert norm_name("Коменданский пр., д.17, корп.1, лит. А,") == norm_name(
        "коменданский пр д 17 корп 1 лит а"
    )
    assert norm_name("Ёлочная") == norm_name("елочная")
    assert (
        iiko_ref([{"system": "hub", "external_id": "x"}, {"system": "iiko", "external_id": "d"}])
        == "d"
    )
    assert iiko_ref([]) is None and iiko_ref(None) is None


# ─── зеркало полей (0059) ───────────────────────────────────────────────────


def test_registry_born_card_follows_registry_until_edited_by_hand():
    site_id = uuid4()
    site = _site("Комендантский пр., д. 17", code="К17", site_id=site_id)
    born = _store(
        "Коменданский пр., д.17,",
        code=None,
        site_id=site_id,
        registry_name="Коменданский пр., д.17,",
        registry_code=None,
    )
    assert {(c.field, c.new) for c in field_changes(born, site)} == {
        ("name", "Комендантский пр., д. 17"),
        ("code", "К17"),
        ("address", "СПб"),
    }
    # имя поправили руками в Hub — за реестром больше не идёт; пустые код и адрес — идут
    edited = _store("Комендантский 17", site_id=site_id, registry_name="Коменданский пр., д.17,")
    assert {(c.field, c.new) for c in field_changes(edited, site)} == {
        ("code", "К17"),
        ("address", "СПб"),
    }


def test_backfilled_card_keeps_its_name_but_gets_empty_address_filled():
    site_id = uuid4()
    site = SiteRow(site_id, "П14", "Приморская ул., д. 14, лит. А", "СПб, Приморская 14", None, "d")
    legacy = _store("Приморская 14", code="П14", site_id=site_id)  # registry_* NULL
    changes = field_changes(legacy, site)
    assert [(c.field, c.old, c.new) for c in changes] == [("address", None, "СПб, Приморская 14")]
    plan = plan_apply([site], [legacy])
    assert plan.refresh == changes and not plan.create and not plan.pending
    # архивная карточка и архивный объект — зеркала нет
    assert not plan_apply([site], [_store("Приморская 14", site_id=site_id, archived=True)]).refresh
    closed = SiteRow(site_id, "П14", "Приморская", "СПб", NOW, "d")
    assert not plan_apply([closed], [legacy]).refresh


def test_stop_rule_sees_linked_live_cards_by_name_without_candidate():
    other_site = uuid4()
    linked = _store("Витебский 101", code="В101", site_id=other_site)
    plan = plan_apply(
        [_site("Витебский 101", code="В102"), _site("Чужой", site_id=other_site)], [linked]
    )
    assert not plan.create
    assert [(p.reason, p.candidate_store_id) for p in plan.pending] == [("name_collision", None)]


def test_field_change_is_plain_data():
    assert FieldChange(uuid4(), "name", "a", "b").field == "name"
