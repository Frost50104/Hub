"""Выгрузка кадровых данных тенанта для импорта в auth.

Часть A хендоффа `HUB_TASK_hr_in_auth.md` (24.09.2026): кадровый процесс
переезжает в auth (решение владельца 21.09). Их `scripts/import_hub_hr.py`
заводит справочники с НАШИМИ id и переносит кадровые поля карточек. Файл —
один на тенант, формат `schema: 1` их импорта; заголовок `counts` обязан
совпасть с длинами списков, иначе импорт откажет.

Только чтение: одна транзакция REPEATABLE READ READ ONLY под RLS тенанта.
Роль приложения — не суперпользователь, поэтому чужой тенант в файл не
попадёт физически; каждая строка вдобавок сверяется по `tenant_id`. Файл — с
правами 0600, а в журнал и stdout идут только числа и id: в файле ФИО и почты.

Кого НЕ выгружаем — архивные карточки людей без `employee_id`. Их импорт
ищет такую карточку по почте среди живых учёток при ЛЮБОМ статусе и при
совпадении молча перезаписывает (`import_hub_hr.py:352-395`). У нас с 0050
ручная архивация обнуляет `employee_id`, а почту уволенного отдают следующему
сотруднику — должность, точка и руководитель уволенного легли бы на учётку
нового. auth таких и не просил («архивные, у которых есть employee_id»).
Ссылка выгружаемой карточки на исключённую (руководитель) пишется `null` —
ровно то же сделал бы их импорт (`manager_unlinked`) — и попадает в отчёт.

Порядок строк стабильный (по id): второй файл в день каткатa даёт чистый diff.

Запуск на VPS (НЕ `source .env` — ломает `cors_origins`):

    systemd-run --wait --pipe --quiet -p EnvironmentFile=/opt/signaris-hub/.env \\
      -p WorkingDirectory=/opt/signaris-hub \\
      /opt/signaris-hub/.venv/bin/python -m app.jobs.export_hr_for_auth \\
      --tenant uppetit --out /root/hr-export/uppetit.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select

from app.db import tenant_scoped_session
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.org import Department, Franchisee, Position, Store
from app.models.shadow import ShadowSite, ShadowTenant

log = structlog.get_logger("jobs.export_hr_for_auth")

SCHEMA = 1
COLLECTIONS = ("positions", "departments", "franchisees", "stores", "profiles", "tu_assignments")
ORG_ROLES = frozenset({"employee", "tu", "franchisee_owner", "office"})


@dataclass
class ExportNotes:
    """Что выгрузка сделала сверх копирования — всё в отчёт, только id."""

    excluded_profile_ids: list[str] = field(default_factory=list)
    managers_nulled: list[str] = field(default_factory=list)
    tu_rows_dropped: int = 0


def is_excluded(profile: Any) -> bool:
    """Архивная карточка человека без учётки — в файл не идёт (см. модуль)."""
    return (
        profile.account_kind == "person"
        and profile.status != "active"
        and profile.employee_id is None
    )


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _iso(value: Any) -> str | None:
    # `isoformat()` с поясом: их импорт разбирает `fromisoformat` без
    # обработки ошибок, кривая строка уронила бы скрипт трейсбеком.
    return None if value is None else value.isoformat()


def _by_id(rows: Iterable[Any]) -> list[Any]:
    return sorted(rows, key=lambda r: str(r.id))


def build_hr_export(
    *,
    tenant_id: UUID,
    exported_at: datetime,
    positions: Sequence[Any],
    departments: Sequence[Any],
    franchisees: Sequence[Any],
    stores: Sequence[Any],
    profiles: Sequence[Any],
    tu_rows: Sequence[Any],
) -> tuple[dict[str, Any], ExportNotes]:
    excluded = {p.id for p in profiles if is_excluded(p)}
    notes = ExportNotes(excluded_profile_ids=sorted(str(i) for i in excluded))

    out_profiles = []
    for p in _by_id(p for p in profiles if p.id not in excluded):
        manager = p.manager_profile_id
        if manager is not None and manager in excluded:
            manager = None
            notes.managers_nulled.append(str(p.id))
        out_profiles.append(
            {
                "id": str(p.id),
                "employee_id": _s(p.employee_id),
                "email": p.email,
                "full_name": p.full_name,
                "account_kind": p.account_kind,
                "status": p.status,
                "archive_reason": p.archive_reason,
                "org_role": p.org_role,
                "position_id": _s(p.position_id),
                "store_id": _s(p.store_id),
                "department_id": _s(p.department_id),
                "franchisee_id": _s(p.franchisee_id),
                "manager_profile_id": _s(manager),
                "hired_at": _iso(p.hired_at),
            }
        )

    kept = {p.id for p in profiles} - excluded
    tu_kept = sorted(
        ((r.profile_id, r.store_id) for r in tu_rows if r.profile_id in kept),
        key=lambda pair: (str(pair[0]), str(pair[1])),
    )
    notes.tu_rows_dropped = len(tu_rows) - len(tu_kept)

    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "tenant_id": str(tenant_id),
        "exported_at": exported_at.isoformat(),
        "counts": {},
        "positions": [
            {
                "id": str(x.id),
                "name": x.name,
                "description": x.description,
                # В Hub это колонка `position` (порядок, NOT NULL DEFAULT 0).
                "sort_order": x.position,
                "archived_at": _iso(x.archived_at),
            }
            for x in _by_id(positions)
        ],
        "departments": [
            {"id": str(x.id), "name": x.name, "parent_id": _s(x.parent_id)}
            for x in _by_id(departments)
        ],
        "franchisees": [
            {
                "id": str(x.id),
                "name": x.name,
                "contact_info": x.contact_info,
                "archived_at": _iso(x.archived_at),
            }
            for x in _by_id(franchisees)
        ],
        "stores": [
            {
                "id": str(x.id),
                "site_id": _s(x.site_id),
                "franchisee_id": _s(x.franchisee_id),
                "archived_at": _iso(x.archived_at),
                "name": x.name,
            }
            for x in _by_id(stores)
        ],
        "profiles": out_profiles,
        "tu_assignments": [
            {"profile_id": str(pid), "store_id": str(sid)} for pid, sid in tu_kept
        ],
    }
    doc["counts"] = {k: len(doc[k]) for k in COLLECTIONS}
    return doc, notes


def structural_problems(doc: dict[str, Any]) -> list[str]:
    """Наши ошибки, при которых файл писать нельзя: их импорт споткнулся бы
    на `UNKNOWN_REF`/`DUPLICATE_ID` или на несходящихся `counts`."""
    problems: list[str] = []
    for k in COLLECTIONS:
        if doc["counts"].get(k) != len(doc[k]):
            problems.append(f"COUNTS {k}: {doc['counts'].get(k)} != {len(doc[k])}")

    ids: dict[str, set[str]] = {}
    for k in ("positions", "departments", "franchisees", "stores", "profiles"):
        seen: set[str] = set()
        for row in doc[k]:
            if row["id"] in seen:
                problems.append(f"DUPLICATE_ID {k} {row['id']}")
            seen.add(row["id"])
        ids[k] = seen

    def ref(where: str, value: str | None, collection: str) -> None:
        if value is not None and value not in ids[collection]:
            problems.append(f"UNKNOWN_REF {where} -> {collection} {value}")

    for d in doc["departments"]:
        ref(f"departments {d['id']}.parent_id", d["parent_id"], "departments")
    for s in doc["stores"]:
        ref(f"stores {s['id']}.franchisee_id", s["franchisee_id"], "franchisees")
    for p in doc["profiles"]:
        where = f"profiles {p['id']}"
        ref(f"{where}.position_id", p["position_id"], "positions")
        ref(f"{where}.department_id", p["department_id"], "departments")
        ref(f"{where}.franchisee_id", p["franchisee_id"], "franchisees")
        ref(f"{where}.store_id", p["store_id"], "stores")
        ref(f"{where}.manager_profile_id", p["manager_profile_id"], "profiles")
    for t in doc["tu_assignments"]:
        ref(f"tu_assignments {t['profile_id']}", t["profile_id"], "profiles")
        ref(f"tu_assignments {t['profile_id']}.store_id", t["store_id"], "stores")
    return problems


def _cycle_members(graph: dict[str, str | None]) -> list[str]:
    """Узлы, лежащие на цикле графа «узел → родитель» (самоссылка — тоже цикл)."""
    on_cycle: set[str] = set()
    for start in graph:
        path: list[str] = []
        cur: str | None = start
        while cur is not None and cur in graph and cur not in path:
            path.append(cur)
            cur = graph[cur]
        if cur is not None and cur in path:
            on_cycle.update(path[path.index(cur) :])
    return sorted(on_cycle)


def auth_blockers_preview(doc: dict[str, Any], known_site_ids: set[str]) -> list[str]:
    """Блокеры их импорта, видные с нашей стороны, — чтобы назвать их в
    ответе ДО их `check`. Файл при этом пишется: решать, править ли данные
    до каткатa, — auth и владельцу, не выгрузке. Только коды и id."""
    out: list[str] = []
    stores = {s["id"]: s for s in doc["stores"]}
    persons = [p for p in doc["profiles"] if p["account_kind"] != "service"]

    for p in persons:
        role = p["org_role"] or "employee"
        if role not in ORG_ROLES:
            out.append(f"ORG_ROLE profiles {p['id']}")
        store = stores.get(p["store_id"]) if p["store_id"] else None
        if store is not None and store["site_id"] is None:
            out.append(f"STORE_WITHOUT_SITE profiles {p['id']} -> store {store['id']}")
        if p["manager_profile_id"] is not None and p["manager_profile_id"] == p["id"]:
            out.append(f"MANAGER_SELF profiles {p['id']}")
    for t in doc["tu_assignments"]:
        store = stores.get(t["store_id"])
        if store is not None and store["site_id"] is None:
            out.append(
                f"STORE_WITHOUT_SITE tu_assignments {t['profile_id']} -> store {store['id']}"
            )

    for s in doc["stores"]:
        if s["site_id"] is not None and s["site_id"] not in known_site_ids:
            out.append(f"SITE_NOT_FOUND stores {s['id']} -> site {s['site_id']}")

    # Франчайзи объекта их импорт берёт из живых магазинов, а если у живых нет —
    # из архивных; больше одного различного значения — конфликт.
    per_site: dict[str, tuple[set[str], set[str]]] = defaultdict(lambda: (set(), set()))
    for s in doc["stores"]:
        if s["site_id"] is not None and s["franchisee_id"] is not None:
            live, archived = per_site[s["site_id"]]
            (live if s["archived_at"] is None else archived).add(s["franchisee_id"])
    for site_id, (live, archived) in sorted(per_site.items()):
        if len(live or archived) > 1:
            out.append(f"SITE_FRANCHISEE_CONFLICT site {site_id}")

    for k in ("positions", "franchisees"):
        for row in doc[k]:
            if not (row["name"] or "").strip():
                out.append(f"EMPTY_NAME {k} {row['id']}")

    parents = {d["id"]: d["parent_id"] for d in doc["departments"]}
    out += [f"DEPARTMENT_CYCLE departments {i}" for i in _cycle_members(parents)]
    managers = {
        p["id"]: p["manager_profile_id"]
        for p in persons
        if p["manager_profile_id"] is not None and p["manager_profile_id"] != p["id"]
    }
    out += [f"MANAGER_CYCLE profiles {i}" for i in _cycle_members(managers)]

    # Карточку без учётки их импорт ищет по почте: две карточки одной почты
    # сопоставятся одной учётке, и победит последняя.
    by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in persons:
        by_email[(p["email"] or "").strip().lower()].append(p)
    for email, group in sorted(by_email.items()):
        if email and len(group) > 1 and any(p["employee_id"] is None for p in group):
            out.append("EMAIL_COLLISION profiles " + ", ".join(sorted(p["id"] for p in group)))
    return out


@dataclass
class TenantRows:
    positions: list[Any]
    departments: list[Any]
    franchisees: list[Any]
    stores: list[Any]
    profiles: list[Any]
    tu_rows: list[Any]
    site_ids: set[str]


async def resolve_tenant(slug: str) -> UUID | None:
    # `shadow_tenants` без RLS; bypass здесь только ради того, что
    # `tenant_scoped_session` без тенанта иначе не открыть.
    async with tenant_scoped_session(None, bypass_rls=True) as db:
        return (
            await db.execute(select(ShadowTenant.id).where(ShadowTenant.slug == slug))
        ).scalar_one_or_none()


async def load_tenant_rows(tenant_id: UUID) -> TenantRows:
    async with tenant_scoped_session(tenant_id) as db:
        # Один снимок на все запросы. Уровень ставится на соединение ДО начала
        # транзакции: листенер RLS открывает её `SELECT set_config(...)`, после
        # которого `SET TRANSACTION` Postgres уже не принимает.
        await db.connection(
            execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True}
        )

        async def rows(model: Any) -> list[Any]:
            return list((await db.execute(select(model))).scalars().all())

        # Без явного rollback(): он «протухает» загруженные объекты, и после
        # закрытия сессии их поля уже не прочитать. Транзакция только читающая —
        # её откатит само закрытие сессии, не трогая загруженные значения.
        return TenantRows(
            positions=await rows(Position),
            departments=await rows(Department),
            franchisees=await rows(Franchisee),
            stores=await rows(Store),
            profiles=await rows(EmployeeProfile),
            tu_rows=await rows(TuStoreAssignment),
            site_ids={str(s) for s in (await db.execute(select(ShadowSite.site_id))).scalars()},
        )


def foreign_rows(tenant_id: UUID, data: TenantRows) -> list[str]:
    """Строки чужого тенанта. Под RLS их быть не может; если есть — значит,
    джоба запущена не той ролью, и файл писать нельзя."""
    problems = []
    for name in ("positions", "departments", "franchisees", "stores", "profiles", "tu_rows"):
        for row in getattr(data, name):
            if row.tenant_id != tenant_id:
                problems.append(f"FOREIGN_TENANT {name} {getattr(row, 'id', row.profile_id)}")
    return problems


def write_export(path: Path, doc: dict[str, Any]) -> None:
    payload = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
        # Файл мог существовать с другими правами — O_CREAT их не трогает.
        os.fchmod(f.fileno(), 0o600)
        f.write(payload)


async def run(slug: str, out: Path) -> int:
    tenant_id = await resolve_tenant(slug)
    if tenant_id is None:
        log.error("hr_export.unknown_tenant", slug=slug)
        return 2
    data = await load_tenant_rows(tenant_id)
    doc, notes = build_hr_export(
        tenant_id=tenant_id,
        exported_at=datetime.now(UTC),
        positions=data.positions,
        departments=data.departments,
        franchisees=data.franchisees,
        stores=data.stores,
        profiles=data.profiles,
        tu_rows=data.tu_rows,
    )
    problems = foreign_rows(tenant_id, data) + structural_problems(doc)
    if problems:
        for p in problems:
            log.error("hr_export.problem", detail=p)
        log.error("hr_export.not_written", problems=len(problems))
        return 1

    write_export(out, doc)
    log.info(
        "hr_export.written", tenant_id=str(tenant_id), slug=slug, file=str(out), **doc["counts"]
    )
    log.info(
        "hr_export.excluded_archived_unlinked",
        count=len(notes.excluded_profile_ids),
        ids=notes.excluded_profile_ids,
    )
    log.info(
        "hr_export.managers_nulled", count=len(notes.managers_nulled), ids=notes.managers_nulled
    )
    log.info("hr_export.tu_rows_dropped", count=notes.tu_rows_dropped)
    blockers = auth_blockers_preview(doc, data.site_ids)
    for b in blockers:
        log.warning("hr_export.auth_blocker_preview", detail=b)
    log.info("hr_export.auth_blockers_preview", count=len(blockers))
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Выгрузка кадровых данных тенанта для импорта в auth"
    )
    parser.add_argument("--tenant", required=True, help="slug тенанта (shadow_tenants.slug)")
    parser.add_argument("--out", required=True, type=Path, help="куда писать JSON (права 0600)")
    args = parser.parse_args()
    return await run(args.tenant, args.out)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
