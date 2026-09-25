"""Кадровые справочники auth (16d): разбор снимка, план и правило точки — без БД."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.services.org_directory_sync import (
    AMBIGUOUS,
    DirRow,
    HubStore,
    TenantDirectory,
    parse_directory,
    plan_directory,
    plan_store_franchisees,
    resolve_site_map,
)

T = uuid4()


def _body(**over) -> dict:
    body = {
        "tenants": [{"tenant_id": str(T), "authoritative": True}],
        "positions": [],
        "departments": [],
        "franchisees": [],
        "site_franchisees": [],
    }
    body.update(over)
    body["totals"] = {
        name: len(body[name])
        for name in ("positions", "departments", "franchisees", "site_franchisees")
    }
    return body


# --- Разбор ---------------------------------------------------------------------


def test_parse_complete_snapshot():
    pid, did, fid, site = uuid4(), uuid4(), uuid4(), uuid4()
    snap = parse_directory(
        _body(
            positions=[
                {
                    "tenant_id": str(T),
                    "id": str(pid),
                    "name": " Бариста ",
                    "description": "",
                    "sort_order": None,
                    "archived_at": None,
                }
            ],
            departments=[
                {"tenant_id": str(T), "id": str(did), "name": "Офис", "parent_id": None,
                 "archived_at": "2026-09-01T00:00:00Z"}
            ],
            franchisees=[
                {"tenant_id": str(T), "id": str(fid), "name": "ИП Иванов", "contact_info": "+7",
                 "archived_at": None}
            ],
            site_franchisees=[
                {"tenant_id": str(T), "site_id": str(site), "franchisee_id": str(fid)}
            ],
        )
    )
    assert snap.tenants == {T: True}
    tenant = snap.for_tenant(T)
    # Пустое описание и пустой порядок — как в Hub (NULL и 0), иначе вечная правка.
    assert tenant.positions[pid] == DirRow(pid, "Бариста", False, None, 0, None)
    assert tenant.departments[did].archived is True
    assert tenant.franchisees[fid].description == "+7"
    assert tenant.site_franchisees == {site: fid}
    assert snap.for_tenant(uuid4()) == TenantDirectory()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["totals"].__setitem__("positions", 3),  # len != totals
        lambda b: b.pop("tenants"),
        lambda b: b["totals"].pop("site_franchisees"),
        lambda b: b["positions"].append({"tenant_id": str(T), "id": "не-uuid", "name": "X"}),
        lambda b: b["franchisees"].append({"tenant_id": str(T), "id": str(uuid4()), "name": " "}),
        lambda b: b["tenants"].append({"tenant_id": str(uuid4())}),  # нет authoritative
    ],
)
def test_parse_rejects_incomplete_or_broken(mutate):
    body = _body(
        positions=[{"tenant_id": str(T), "id": str(uuid4()), "name": "Кассир", "archived_at": None}]
    )
    mutate(body)
    # Строку, добавленную в коллекцию, totals не учитывает — тоже расхождение.
    with pytest.raises(ValueError):
        parse_directory(body)


# --- План: должности и франчайзи ---------------------------------------------------


def _dir(**rows: dict[UUID, DirRow]) -> TenantDirectory:
    return TenantDirectory(**rows)


def _actions(plan) -> set[tuple[str, str, UUID]]:
    return {(op.kind, op.action, op.id) for op in plan.ops}


def test_plan_create_archive_rename_restore_update():
    new, gone, renamed, back, desc = (uuid4() for _ in range(5))
    auth = _dir(
        positions={
            new: DirRow(new, "Пекарь", False, None, 3),
            gone: DirRow(gone, "Старая", True, None, 0),
            renamed: DirRow(renamed, "Старший бариста", False, None, 0),
            back: DirRow(back, "Повар", False, None, 0),
            desc: DirRow(desc, "Кассир", False, "Смены", 1),
        }
    )
    hub = _dir(
        positions={
            gone: DirRow(gone, "Старая", False, None, 0),
            renamed: DirRow(renamed, "Бариста", False, None, 0),
            back: DirRow(back, "Повар", True, None, 0),
            desc: DirRow(desc, "Кассир", False, None, 1),
        }
    )
    plan = plan_directory(auth, hub)
    assert _actions(plan) == {
        ("position", "create", new),
        ("position", "archive", gone),
        ("position", "rename", renamed),
        ("position", "restore", back),
        ("position", "update", desc),
    }
    update = next(op for op in plan.ops if op.action == "update")
    assert update.values == (("description", "Смены"),)
    assert plan.skips == {} and plan.hub_only == {}


def test_plan_same_directory_is_empty():
    pid, fid = uuid4(), uuid4()
    rows = _dir(
        positions={pid: DirRow(pid, "Бариста", False, None, 2)},
        franchisees={fid: DirRow(fid, "ИП", False, "+7")},
    )
    assert plan_directory(rows, rows).ops == []


def test_plan_swap_and_chain_are_plain_renames():
    """Обмен имён и цепочка — обычные переименования: конфликт снимает
    двухпроходное применение, план их не пропускает."""
    a, b, c = uuid4(), uuid4(), uuid4()
    auth = _dir(
        positions={
            a: DirRow(a, "Y", False, None, 0),
            b: DirRow(b, "X", False, None, 0),  # обмен X↔Y
            c: DirRow(c, "Z", False, None, 0),
        }
    )
    hub = _dir(
        positions={
            a: DirRow(a, "X", False, None, 0),
            b: DirRow(b, "Y", False, None, 0),
            c: DirRow(c, "Y2", False, None, 0),
        }
    )
    plan = plan_directory(auth, hub)
    assert {op.action for op in plan.ops} == {"rename"}
    assert plan.skips == {}


def test_plan_conflict_with_hub_only_row_is_skipped():
    """Строку, созданную в Hub после выгрузки, план не трогает, а её имя
    не занимает ни создание, ни переименование, ни восстановление."""
    hub_only, new, renamed, back = uuid4(), uuid4(), uuid4(), uuid4()
    auth = _dir(
        franchisees={
            new: DirRow(new, "ИП Петров", False),
            renamed: DirRow(renamed, "ип петров", False),
            back: DirRow(back, "ИП ПЕТРОВ", False),
        }
    )
    hub = _dir(
        franchisees={
            hub_only: DirRow(hub_only, "ИП Петров", False),
            renamed: DirRow(renamed, "ИП Иванов", False),
            back: DirRow(back, "ИП ПЕТРОВ", True),
        }
    )
    plan = plan_directory(auth, hub)
    assert plan.ops == []
    assert sorted(plan.skips["name_conflict"]) == sorted(str(x) for x in (new, renamed, back))
    assert plan.hub_only == {"franchisee": [str(hub_only)]}


def test_plan_archived_row_rename_never_conflicts():
    hub_only, arch = uuid4(), uuid4()
    auth = _dir(positions={arch: DirRow(arch, "Кассир", True, None, 0)})
    hub = _dir(
        positions={
            hub_only: DirRow(hub_only, "Кассир", False, None, 0),
            arch: DirRow(arch, "Кассир старый", True, None, 0),
        }
    )
    plan = plan_directory(auth, hub)
    assert _actions(plan) == {("position", "rename", arch)}


def test_plan_creates_row_archived_in_auth():
    """Строка, которую auth прислал уже архивной, а в Hub её не было: создаём
    архивной — иначе карточки со ссылкой на неё вечно ловили бы unknown_ref."""
    gone = uuid4()
    plan = plan_directory(_dir(positions={gone: DirRow(gone, "Было", True, None, 0)}), _dir())
    (op,) = plan.ops
    assert op.action == "create" and op.get("archived") is True


# --- План: отделы ---------------------------------------------------------------------


def test_departments_created_then_parented_in_any_order():
    parent, child = uuid4(), uuid4()
    auth = _dir(
        departments={
            # ребёнок раньше родителя (снимок сортирован по имени)
            child: DirRow(child, "Аналитика", False, parent_id=parent),
            parent: DirRow(parent, "Офис", False),
        }
    )
    plan = plan_directory(auth, _dir())
    ordered = [(op.action, op.id) for op in plan.sorted_ops()]
    assert ordered.index(("create", parent)) < ordered.index(("reparent", child))
    assert ordered.index(("create", child)) < ordered.index(("reparent", child))
    reparent = next(op for op in plan.ops if op.action == "reparent")
    assert reparent.get("parent_id") == parent


def test_department_cycle_and_unknown_parent_are_skipped():
    a, b, c, ghost = uuid4(), uuid4(), uuid4(), uuid4()
    auth = _dir(
        departments={
            a: DirRow(a, "A", False, parent_id=b),
            b: DirRow(b, "B", False, parent_id=a),
            c: DirRow(c, "C", False, parent_id=ghost),
        }
    )
    hub = _dir(
        departments={
            a: DirRow(a, "A", False),
            b: DirRow(b, "B", False),
            c: DirRow(c, "C", False),
        }
    )
    plan = plan_directory(auth, hub)
    assert sorted(plan.skips["dept_cycle"]) == sorted([str(a), str(b)])
    assert plan.skips["unknown_parent"] == [str(c)]
    assert not [op for op in plan.ops if op.action == "reparent"]


def test_department_archive_and_restore():
    a, b = uuid4(), uuid4()
    auth = _dir(departments={a: DirRow(a, "A", True), b: DirRow(b, "B", False)})
    hub = _dir(departments={a: DirRow(a, "A", False), b: DirRow(b, "B", True)})
    assert _actions(plan_directory(auth, hub)) == {
        ("department", "archive", a),
        ("department", "restore", b),
    }


# --- Правило точки и франчайзи точек ----------------------------------------------------


def test_site_map_rule():
    one, dup, arch_only, two_arch, live_and_arch = (uuid4() for _ in range(5))
    s1 = HubStore(uuid4(), one, None, False)
    d1, d2 = HubStore(uuid4(), dup, None, False), HubStore(uuid4(), dup, None, False)
    a1 = HubStore(uuid4(), arch_only, None, True)
    t1, t2 = HubStore(uuid4(), two_arch, None, True), HubStore(uuid4(), two_arch, None, True)
    la_live = HubStore(uuid4(), live_and_arch, None, False)
    la_arch = HubStore(uuid4(), live_and_arch, None, True)
    no_site = HubStore(uuid4(), None, None, False)
    site_map = resolve_site_map([s1, d1, d2, a1, t1, t2, la_live, la_arch, no_site])
    assert site_map == {
        one: s1.id,
        dup: AMBIGUOUS,
        arch_only: a1.id,
        two_arch: AMBIGUOUS,
        live_and_arch: la_live.id,
    }


def test_store_franchisees_follow_resolved_store_only():
    fid, other_fid = uuid4(), uuid4()
    site_ok, site_dup, site_clear, site_same = (uuid4() for _ in range(4))
    ok = HubStore(uuid4(), site_ok, None, False)
    dup1, dup2 = HubStore(uuid4(), site_dup, None, False), HubStore(uuid4(), site_dup, None, False)
    clear = HubStore(uuid4(), site_clear, other_fid, False)
    same = HubStore(uuid4(), site_same, fid, False)
    no_site = HubStore(uuid4(), None, other_fid, False)
    stores = [ok, dup1, dup2, clear, same, no_site]
    auth = TenantDirectory(
        site_franchisees={site_ok: fid, site_dup: fid, site_same: fid}
    )
    from app.services.org_directory_sync import DirectoryPlan

    plan = DirectoryPlan()
    plan_store_franchisees(plan, auth, stores, resolve_site_map(stores), {fid, other_fid})
    assert {(op.id, op.get("franchisee_id")) for op in plan.ops} == {
        (ok.id, fid),  # объект с франчайзи — ставим
        (clear.id, None),  # объекта нет в списке — франчайзи у точки нет
    }


def test_store_franchisee_unknown_ref_is_skipped():
    site, ghost = uuid4(), uuid4()
    store = HubStore(uuid4(), site, None, False)
    from app.services.org_directory_sync import DirectoryPlan

    plan = DirectoryPlan()
    auth = TenantDirectory(site_franchisees={site: ghost})
    plan_store_franchisees(plan, auth, [store], resolve_site_map([store]), set())
    assert plan.ops == [] and plan.skips == {"unknown_ref": [str(store.id)]}


def test_canonical_is_stable_and_plain():
    rid = uuid4()
    plan = plan_directory(
        _dir(positions={rid: DirRow(rid, "Новая", False, "Описание", 5)}), _dir()
    )
    (op,) = plan.ops
    assert op.canonical() == [
        "position",
        "create",
        str(rid),
        [
            ["name", "Новая"],
            ["archived", "False"],
            ["description", "Описание"],
            ["sort_order", "5"],
        ],
    ]
