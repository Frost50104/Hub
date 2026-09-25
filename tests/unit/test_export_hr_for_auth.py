"""Выгрузка кадровых данных для импорта в auth (часть A `HUB_TASK_hr_in_auth`).

Чистые функции: состав файла, сериализация, наши структурные ошибки и
предпросмотр блокеров их `import_hub_hr.py`. Загрузка из БД и запись файла —
в `tests/integration/test_export_hr_for_auth.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.jobs.export_hr_for_auth import (
    COLLECTIONS,
    _cycle_members,
    auth_blockers_preview,
    build_hr_export,
    structural_problems,
)

T = uuid4()
NOW = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)


def _id(n: int) -> UUID:
    return UUID(int=n)


def _profile(n: int, **kw) -> SimpleNamespace:
    base = {
        "id": _id(n),
        "tenant_id": T,
        "employee_id": uuid4(),
        "email": f"p{n}@t.ru",
        "full_name": f"Человек {n}",
        "account_kind": "person",
        "status": "active",
        "archive_reason": None,
        "org_role": "employee",
        "position_id": None,
        "store_id": None,
        "department_id": None,
        "franchisee_id": None,
        "manager_profile_id": None,
        "hired_at": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _store(n: int, **kw) -> SimpleNamespace:
    base = {"id": _id(n), "tenant_id": T, "site_id": uuid4(), "franchisee_id": None,
            "archived_at": None, "name": f"Точка {n}"}
    base.update(kw)
    return SimpleNamespace(**base)


def _build(*, profiles=(), stores=(), tu_rows=(), positions=(), departments=(), franchisees=()):
    return build_hr_export(
        tenant_id=T,
        exported_at=NOW,
        positions=list(positions),
        departments=list(departments),
        franchisees=list(franchisees),
        stores=list(stores),
        profiles=list(profiles),
        tu_rows=list(tu_rows),
    )


def test_archived_unlinked_person_is_excluded_and_references_become_null():
    gone = _profile(1, status="archived", archive_reason="manual", employee_id=None)
    boss_ref = _profile(2, manager_profile_id=gone.id)
    kept_archived = _profile(3, status="archived", archive_reason="auto_inactivity")
    cash = _profile(4, account_kind="service", employee_id=None)
    store = _store(10)
    tu = [
        SimpleNamespace(profile_id=gone.id, store_id=store.id, tenant_id=T),
        SimpleNamespace(profile_id=boss_ref.id, store_id=store.id, tenant_id=T),
    ]

    doc, notes = _build(profiles=[gone, boss_ref, kept_archived, cash], stores=[store], tu_rows=tu)

    ids = [p["id"] for p in doc["profiles"]]
    # Архивная без учётки выпала; архивная С учёткой и касса без учётки — остались.
    assert ids == [str(boss_ref.id), str(kept_archived.id), str(cash.id)]
    assert doc["profiles"][0]["manager_profile_id"] is None
    assert notes.excluded_profile_ids == [str(gone.id)]
    assert notes.managers_nulled == [str(boss_ref.id)]
    assert notes.tu_rows_dropped == 1
    assert doc["tu_assignments"] == [{"profile_id": str(boss_ref.id), "store_id": str(store.id)}]
    assert doc["counts"] == {k: len(doc[k]) for k in COLLECTIONS}
    assert structural_problems(doc) == []


def test_serialization_is_parseable_and_stable():
    archived = datetime(2026, 9, 19, 20, 17, 5, 123456, tzinfo=UTC)
    position = SimpleNamespace(id=_id(7), tenant_id=T, name="Бариста", description=None,
                               position=3, archived_at=archived)
    p2 = _profile(2, hired_at=date(2024, 3, 1), position_id=position.id)
    p1 = _profile(1)

    doc, _ = _build(profiles=[p2, p1], positions=[position])

    assert doc["schema"] == 1 and doc["tenant_id"] == str(T)
    assert [p["id"] for p in doc["profiles"]] == [str(p1.id), str(p2.id)]  # по id
    assert doc["profiles"][1]["hired_at"] == "2024-03-01"
    row = doc["positions"][0]
    assert row["sort_order"] == 3
    # Их импорт разбирает `fromisoformat` без обработки ошибок.
    assert datetime.fromisoformat(row["archived_at"]) == archived
    assert datetime.fromisoformat(doc["exported_at"]) == NOW


def test_structural_problems_catch_dangling_refs_duplicates_and_counts():
    doc, _ = _build(profiles=[_profile(1, position_id=_id(99))], stores=[_store(5), _store(5)])
    doc["counts"]["tu_assignments"] = 3

    problems = structural_problems(doc)

    assert any(p.startswith("UNKNOWN_REF profiles") and str(_id(99)) in p for p in problems)
    assert f"DUPLICATE_ID stores {_id(5)}" in problems
    assert "COUNTS tu_assignments: 3 != 0" in problems


def test_blockers_preview_mirrors_their_import():
    no_site = _store(10, site_id=None)
    site = uuid4()
    live_a = _store(11, site_id=site, franchisee_id=_id(81))
    live_b = _store(12, site_id=site, franchisee_id=_id(82))
    orphan_site = _store(13, site_id=uuid4())
    franchisees = [SimpleNamespace(id=_id(n), tenant_id=T, name="Ф", contact_info=None,
                                   archived_at=None) for n in (81, 82)]
    departments = [
        SimpleNamespace(id=_id(21), tenant_id=T, name="А", parent_id=_id(22)),
        SimpleNamespace(id=_id(22), tenant_id=T, name="Б", parent_id=_id(21)),
        SimpleNamespace(id=_id(23), tenant_id=T, name="Сам себе", parent_id=_id(23)),
    ]
    profiles = [
        _profile(1, store_id=no_site.id),
        _profile(2, account_kind="service", store_id=no_site.id),  # касса — не блокер
        _profile(3, manager_profile_id=_id(3)),
        _profile(4, manager_profile_id=_id(5)),
        _profile(5, manager_profile_id=_id(4)),
        _profile(6, org_role="boss"),
        _profile(7, employee_id=None, email="Same@t.ru"),
        _profile(8, email="same@t.ru"),
    ]
    doc, _ = _build(profiles=profiles, stores=[no_site, live_a, live_b, orphan_site],
                    departments=departments, franchisees=franchisees)
    known_sites = {str(site), str(no_site.site_id), str(live_a.site_id)}

    got = auth_blockers_preview(doc, known_sites)

    assert f"STORE_WITHOUT_SITE profiles {_id(1)} -> store {no_site.id}" in got
    assert not any(str(_id(2)) in b for b in got)
    assert f"MANAGER_SELF profiles {_id(3)}" in got
    assert {f"MANAGER_CYCLE profiles {_id(4)}", f"MANAGER_CYCLE profiles {_id(5)}"} <= set(got)
    assert f"ORG_ROLE profiles {_id(6)}" in got
    assert f"SITE_FRANCHISEE_CONFLICT site {site}" in got
    assert f"SITE_NOT_FOUND stores {orphan_site.id} -> site {orphan_site.site_id}" in got
    assert {f"DEPARTMENT_CYCLE departments {_id(n)}" for n in (21, 22, 23)} <= set(got)
    collision = [b for b in got if b.startswith("EMAIL_COLLISION")]
    assert collision == [f"EMAIL_COLLISION profiles {_id(7)}, {_id(8)}"]
    assert not any("@" in b for b in got)  # ни одной почты в отчёте


def test_franchisee_of_site_falls_back_to_archived_only_without_live():
    site = uuid4()
    stores = [
        _store(1, site_id=site, franchisee_id=_id(81)),
        _store(2, site_id=site, franchisee_id=_id(82), archived_at=NOW),  # живой есть — не в счёт
    ]
    franchisees = [SimpleNamespace(id=_id(n), tenant_id=T, name="Ф", contact_info=None,
                                   archived_at=None) for n in (81, 82)]
    doc, _ = _build(stores=stores, franchisees=franchisees)
    assert auth_blockers_preview(doc, {str(site)}) == []


def test_cycle_members():
    assert _cycle_members({"a": "b", "b": "a", "c": "a", "d": None}) == ["a", "b"]
    assert _cycle_members({"x": "x"}) == ["x"]
    assert _cycle_members({"a": "b", "b": None}) == []
