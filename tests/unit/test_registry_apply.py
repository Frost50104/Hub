"""Правила применения реестра к магазинам (`registry_apply.plan_apply`).

Интеграционные тесты в CI не бегут, а здесь ровно те решения, которые
стоят денег: создать дубль, заархивировать не то, воскресить архивное.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.services.registry_apply import (
    SiteRow,
    StoreRow,
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


def _store(name, *, code=None, site_id=None, archived=False):
    return StoreRow(
        id=uuid4(), name=name, code=code, site_id=site_id, archived_at=NOW if archived else None
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


def test_stop_rule_ignores_linked_and_archived_stores():
    other_site = uuid4()
    linked = _store("Витебский 101", code="В101", site_id=other_site)
    archived = _store("Витебский 101", code="В101", archived=True)
    site = _site()
    plan = plan_apply([site, _site("Чужой", site_id=other_site)], [linked, archived])
    assert plan.create == [site], "занятая и архивная карточки дубль не образуют"


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
