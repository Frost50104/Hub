"""Снимок кадровых справочников auth (16d): должности, франчайзи, отделы, франчайзи точек.

Канал — `GET /api/products/org-directory?product=hub` под `staff_service_key`
(метка hub, скоуп `hr_export`). Каждый прогон синка штата — ПЕРЕД штатом:
строки штата ссылаются на справочники, а мониторинг auth ждёт оба маршрута.

Свойства, на которых стоит модуль:
- **Снимок цельный или никакой.** `len(коллекции) == totals[коллекция]` по всем
  четырём коллекциям и разбор каждой строки — до любых решений. Неполный снимок,
  битая строка, 403, 404, сбой сети → None: применять нечего, а состояние
  заморозки не трогаем (сбой не должен снимать заморозку).
- **Только upsert, никогда не удалять** (контракт): архивные строки приходят с
  `archived_at` — архивируем свою; строк, которых нет в снимке, не трогаем.
- **Порядок применения** — архив → переименование → создание → восстановление.
  Переименование в два прохода через временное имя: иначе цепочка «A→X, пока X
  у B» и обмен «A:X ↔ B:Y» нарушают `uq_positions_active_name` /
  `uq_franchisees_active_name` посередине. Конфликт с живой строкой, которой в
  снимке нет (создана в Hub после выгрузки), планировщик находит заранее и
  пропускает операцию с кодом `name_conflict` — применение до IntegrityError не
  доходит, savepoint на операцию остаётся страховкой.
- **Отделы** уникальных имён не имеют; новые создаются без родителя, родители
  ставятся вторым шагом, когда все отделы уже есть, — порядок строк в снимке
  (по имени) не важен. Цикл в итоговом дереве — пропуск `dept_cycle`.
- **`site_franchisees`** — единственный канал франчайзи точки: только для
  магазина, найденного правилом точки; объекта нет в списке → франчайзи
  магазина очищаем; магазины без `site_id` не трогаем.

Тело несёт названия юрлиц и контакты франчайзи — в логи только числа и id.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.org import Department, Franchisee, Position, Store
from app.services.auth_http import disabled_code

log = structlog.get_logger("org_directory_sync")

COLLECTIONS = ("positions", "departments", "franchisees", "site_franchisees")
DISABLED_CODE = "hr_export_disabled"

# Сайт с несколькими живыми магазинами (дубли) или только архивными — не
# сопоставлен однозначно; поле карточки не трогаем.
AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class DirRow:
    """Строка справочника — одна форма для auth и Hub.

    `description` — описание должности или контакты франчайзи; `sort_order` —
    только у должностей (в Hub колонка `position`); `parent_id` — у отделов.
    """

    id: UUID
    name: str
    archived: bool
    description: str | None = None
    sort_order: int | None = None
    parent_id: UUID | None = None


@dataclass
class TenantDirectory:
    positions: dict[UUID, DirRow] = field(default_factory=dict)
    franchisees: dict[UUID, DirRow] = field(default_factory=dict)
    departments: dict[UUID, DirRow] = field(default_factory=dict)
    # site_id → franchisee_id
    site_franchisees: dict[UUID, UUID] = field(default_factory=dict)


@dataclass
class DirectorySnapshot:
    # tenant_id → authoritative. Тенанта с hr_mode NULL в снимке НЕТ.
    tenants: dict[UUID, bool]
    by_tenant: dict[UUID, TenantDirectory]

    def for_tenant(self, tenant_id: UUID) -> TenantDirectory:
        return self.by_tenant.get(tenant_id) or TenantDirectory()


@dataclass(frozen=True)
class HubStore:
    id: UUID
    site_id: UUID | None
    franchisee_id: UUID | None
    archived: bool


# --- Разбор ответа -------------------------------------------------------------


class _Incomplete(ValueError):
    """Снимок нельзя применять — причина уходит в лог числами, без ПДн."""


def _uuid(value: Any) -> UUID:
    if value is None:
        raise _Incomplete("uuid")
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise _Incomplete("uuid") from exc


def _opt_uuid(value: Any) -> UUID | None:
    return None if value is None else _uuid(value)


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Incomplete("name")
    return value.strip()


def _opt_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _Incomplete("text")
    return clean_text(value)


def clean_text(value: str | None) -> str | None:
    """Пустое описание = нет описания — с обеих сторон одинаково. Иначе "" из
    auth против NULL в Hub давали бы «изменение» на каждом прогоне, и приёмка
    каткатa «0 изменений» была бы недостижима."""
    if value is None:
        return None
    return value if value.strip() else None


def parse_directory(data: Any) -> DirectorySnapshot:
    """Ответ `/org-directory` → снимок. Любое расхождение — `_Incomplete`."""
    if not isinstance(data, dict):
        raise _Incomplete("body")
    totals = data.get("totals")
    if not isinstance(totals, dict):
        raise _Incomplete("totals")
    for name in COLLECTIONS:
        items = data.get(name)
        if not isinstance(items, list):
            raise _Incomplete(name)
        total = totals.get(name)
        if not isinstance(total, int) or isinstance(total, bool) or total != len(items):
            raise _Incomplete(f"{name}_total")

    tenants_raw = data.get("tenants")
    if not isinstance(tenants_raw, list):
        raise _Incomplete("tenants")
    tenants: dict[UUID, bool] = {}
    for item in tenants_raw:
        if not isinstance(item, dict) or not isinstance(item.get("authoritative"), bool):
            raise _Incomplete("tenants")
        tenants[_uuid(item.get("tenant_id"))] = item["authoritative"]

    by_tenant: dict[UUID, TenantDirectory] = {}

    def bucket(item: Any) -> tuple[TenantDirectory, dict]:
        if not isinstance(item, dict):
            raise _Incomplete("row")
        return by_tenant.setdefault(_uuid(item.get("tenant_id")), TenantDirectory()), item

    for raw in data["positions"]:
        tenant, item = bucket(raw)
        sort_order = item.get("sort_order")
        if sort_order is None:
            sort_order = 0  # в Hub колонка NOT NULL DEFAULT 0 — то же «без порядка»
        elif not isinstance(sort_order, int) or isinstance(sort_order, bool):
            raise _Incomplete("sort_order")
        row = DirRow(
            id=_uuid(item.get("id")),
            name=_name(item.get("name")),
            archived=item.get("archived_at") is not None,
            description=_opt_text(item.get("description")),
            sort_order=sort_order,
        )
        tenant.positions[row.id] = row
    for raw in data["franchisees"]:
        tenant, item = bucket(raw)
        row = DirRow(
            id=_uuid(item.get("id")),
            name=_name(item.get("name")),
            archived=item.get("archived_at") is not None,
            description=_opt_text(item.get("contact_info")),
        )
        tenant.franchisees[row.id] = row
    for raw in data["departments"]:
        tenant, item = bucket(raw)
        row = DirRow(
            id=_uuid(item.get("id")),
            name=_name(item.get("name")),
            archived=item.get("archived_at") is not None,
            parent_id=_opt_uuid(item.get("parent_id")),
        )
        tenant.departments[row.id] = row
    for raw in data["site_franchisees"]:
        tenant, item = bucket(raw)
        tenant.site_franchisees[_uuid(item.get("site_id"))] = _uuid(item.get("franchisee_id"))
    return DirectorySnapshot(tenants=tenants, by_tenant=by_tenant)


async def fetch_org_directory(*, timeout: float = 20.0) -> DirectorySnapshot | None:
    """Полный снимок справочников или None (нет доступа, выключено, сеть, неполный).

    Единственная точка HTTP модуля — тесты подменяют её целиком.
    """
    settings = get_settings()
    if not settings.staff_service_key:
        return None
    url = f"{settings.signaris_auth_base_url}/api/products/org-directory"
    try:
        async with httpx.AsyncClient(
            headers={"X-Service-Key": settings.staff_service_key}, timeout=timeout
        ) as client:
            resp = await client.get(url, params={"product": "hub"})
    except httpx.HTTPError as exc:
        log.warning("hr_sync.directory_fetch_failed", error=type(exc).__name__)
        return None
    if resp.status_code in (401, 403):
        # Ключ без скоупа hr_export или ещё не выдан — ожидаемо, без шторма.
        log.info("hr_sync.directory_unavailable", status=resp.status_code)
        return None
    if resp.status_code == 404:
        code = disabled_code(resp)
        if code == DISABLED_CODE:
            log.info("hr_sync.directory_unavailable", status=404, code=code)
        else:
            # Голый 404 неотличим от опечатки в base_url — только с полным URL.
            log.warning("hr_sync.directory_bare_404", url=str(resp.request.url))
        return None
    if resp.status_code != 200:
        log.warning("hr_sync.directory_fetch_failed", status=resp.status_code)
        return None
    try:
        return parse_directory(resp.json())
    except ValueError as exc:  # _Incomplete и не-JSON
        log.warning("hr_sync.directory_incomplete", reason=str(exc) or type(exc).__name__)
        return None


# --- Загрузка состояния Hub ------------------------------------------------------


async def load_hub_directory(db: AsyncSession) -> tuple[TenantDirectory, list[HubStore]]:
    """Справочники и магазины тенанта сессии (RLS) в той же форме, что снимок."""
    hub = TenantDirectory()
    for row in (await db.execute(select(Position))).scalars():
        hub.positions[row.id] = DirRow(
            id=row.id,
            name=row.name,
            archived=row.archived_at is not None,
            description=clean_text(row.description),
            sort_order=row.position,
        )
    for row in (await db.execute(select(Franchisee))).scalars():
        hub.franchisees[row.id] = DirRow(
            id=row.id,
            name=row.name,
            archived=row.archived_at is not None,
            description=clean_text(row.contact_info),
        )
    for row in (await db.execute(select(Department))).scalars():
        hub.departments[row.id] = DirRow(
            id=row.id,
            name=row.name,
            archived=row.archived_at is not None,
            parent_id=row.parent_id,
        )
    stores = [
        HubStore(
            id=s.id,
            site_id=s.site_id,
            franchisee_id=s.franchisee_id,
            archived=s.archived_at is not None,
        )
        for s in (await db.execute(select(Store))).scalars()
    ]
    return hub, stores


# --- Правило точки ---------------------------------------------------------------


def resolve_site_map(stores: Iterable[HubStore]) -> dict[UUID, UUID | str]:
    """Объект реестра → магазин Hub (контракт 16d, правило точки).

    Один живой магазин на объекте — он; живых нет и архивный один — он; иначе
    `AMBIGUOUS` (дубли или несколько архивных) — поле карточки не трогаем.
    """
    by_site: dict[UUID, list[HubStore]] = {}
    for store in stores:
        if store.site_id is not None:
            by_site.setdefault(store.site_id, []).append(store)
    result: dict[UUID, UUID | str] = {}
    for site_id, group in by_site.items():
        live = [s for s in group if not s.archived]
        if len(live) == 1:
            result[site_id] = live[0].id
        elif not live and len(group) == 1:
            result[site_id] = group[0].id
        else:
            result[site_id] = AMBIGUOUS
    return result


# --- План -----------------------------------------------------------------------


@dataclass(frozen=True)
class DirOp:
    kind: str  # position | franchisee | department | store
    action: str  # archive | rename | update | create | restore | reparent | franchisee
    id: UUID
    values: tuple[tuple[str, Any], ...] = ()

    def get(self, key: str) -> Any:
        return dict(self.values).get(key)

    def canonical(self) -> list[Any]:
        return [
            self.kind,
            self.action,
            str(self.id),
            [[k, None if v is None else str(v)] for k, v in self.values],
        ]


# Порядок применения; внутри действия — по id (стабильный порядок замков).
_ACTION_ORDER = {
    "archive": 0,
    "rename": 1,
    "update": 2,
    "create": 3,
    "restore": 4,
    "reparent": 5,
    "franchisee": 6,
}


@dataclass
class DirectoryPlan:
    ops: list[DirOp] = field(default_factory=list)
    # код → id строк (в отчёт и в лог; без названий)
    skips: dict[str, list[str]] = field(default_factory=dict)
    # строки Hub, которых нет в снимке: kind → id
    hub_only: dict[str, list[str]] = field(default_factory=dict)

    def skip(self, code: str, row_id: UUID) -> None:
        self.skips.setdefault(code, []).append(str(row_id))

    def sorted_ops(self) -> list[DirOp]:
        return sorted(self.ops, key=lambda op: (_ACTION_ORDER[op.action], op.kind, str(op.id)))

    def created_ids(self) -> set[UUID]:
        return {op.id for op in self.ops if op.action == "create"}


def _norm(name: str) -> str:
    return name.strip().lower()


def _plan_named(
    plan: DirectoryPlan,
    kind: str,
    auth_rows: dict[UUID, DirRow],
    hub_rows: dict[UUID, DirRow],
    *,
    extra_fields: tuple[str, ...],
) -> None:
    """Должности и франчайзи: имена живых строк уникальны (partial index)."""
    hub_only = [rid for rid in hub_rows if rid not in auth_rows]
    if hub_only:
        plan.hub_only[kind] = sorted(str(r) for r in hub_only)
    taken_by_hub_only = {_norm(hub_rows[r].name) for r in hub_only if not hub_rows[r].archived}
    final_active = Counter(_norm(r.name) for r in auth_rows.values() if not r.archived)

    for row_id in sorted(auth_rows, key=str):
        a = auth_rows[row_id]
        h = hub_rows.get(row_id)
        conflict = not a.archived and (
            _norm(a.name) in taken_by_hub_only or final_active[_norm(a.name)] > 1
        )
        extra = tuple((f, getattr(a, f)) for f in extra_fields)
        if h is None:
            if conflict:
                plan.skip("name_conflict", row_id)
                continue
            plan.ops.append(
                DirOp(kind, "create", row_id, (("name", a.name), ("archived", a.archived), *extra))
            )
            continue
        if a.archived and not h.archived:
            plan.ops.append(DirOp(kind, "archive", row_id))
        if a.name != h.name:
            if conflict:
                plan.skip("name_conflict", row_id)
            else:
                plan.ops.append(DirOp(kind, "rename", row_id, (("name", a.name),)))
        changed = tuple((f, v) for f, v in extra if getattr(h, f) != v)
        if changed:
            plan.ops.append(DirOp(kind, "update", row_id, changed))
        if not a.archived and h.archived:
            if conflict:
                plan.skip("name_conflict", row_id)
            else:
                plan.ops.append(DirOp(kind, "restore", row_id))


def _plan_departments(
    plan: DirectoryPlan, auth_rows: dict[UUID, DirRow], hub_rows: dict[UUID, DirRow]
) -> None:
    hub_only = [rid for rid in hub_rows if rid not in auth_rows]
    if hub_only:
        plan.hub_only["department"] = sorted(str(r) for r in hub_only)
    known = set(auth_rows) | set(hub_rows)
    # Итоговое дерево: родители из снимка, у строк только из Hub — свои.
    final_parent: dict[UUID, UUID | None] = {r: hub_rows[r].parent_id for r in hub_only}
    for row_id, a in auth_rows.items():
        final_parent[row_id] = a.parent_id if a.parent_id in known else None

    def cyclic(start: UUID) -> bool:
        seen = {start}
        node = final_parent.get(start)
        while node is not None:
            if node in seen:
                return True
            seen.add(node)
            node = final_parent.get(node)
        return False

    for row_id in sorted(auth_rows, key=str):
        a = auth_rows[row_id]
        h = hub_rows.get(row_id)
        if h is None:
            plan.ops.append(
                DirOp("department", "create", row_id, (("name", a.name), ("archived", a.archived)))
            )
            current_parent = None
        else:
            if a.archived and not h.archived:
                plan.ops.append(DirOp("department", "archive", row_id))
            if a.name != h.name:
                plan.ops.append(DirOp("department", "rename", row_id, (("name", a.name),)))
            if not a.archived and h.archived:
                plan.ops.append(DirOp("department", "restore", row_id))
            current_parent = h.parent_id
        if a.parent_id is not None and a.parent_id not in known:
            plan.skip("unknown_parent", row_id)
            continue
        if a.parent_id != current_parent:
            if a.parent_id is not None and cyclic(row_id):
                plan.skip("dept_cycle", row_id)
                continue
            plan.ops.append(DirOp("department", "reparent", row_id, (("parent_id", a.parent_id),)))


def plan_directory(auth: TenantDirectory, hub: TenantDirectory) -> DirectoryPlan:
    """Что поменять в справочниках Hub, чтобы они совпали со снимком (чисто)."""
    plan = DirectoryPlan()
    _plan_named(
        plan, "position", auth.positions, hub.positions, extra_fields=("description", "sort_order")
    )
    _plan_named(
        plan, "franchisee", auth.franchisees, hub.franchisees, extra_fields=("description",)
    )
    _plan_departments(plan, auth.departments, hub.departments)
    return plan


def plan_store_franchisees(
    plan: DirectoryPlan,
    auth: TenantDirectory,
    stores: Iterable[HubStore],
    site_map: dict[UUID, UUID | str],
    known_franchisees: set[UUID],
) -> None:
    """Франчайзи магазинов по `site_franchisees` — в тот же план (чисто).

    Только магазин, найденный правилом точки: у объекта-дубля (`AMBIGUOUS`) и у
    архивного магазина рядом с живым франчайзи не трогаем.
    """
    for store in sorted(stores, key=lambda s: str(s.id)):
        if store.site_id is None or site_map.get(store.site_id) != store.id:
            continue
        wanted = auth.site_franchisees.get(store.site_id)
        if wanted is not None and wanted not in known_franchisees:
            plan.skip("unknown_ref", store.id)
            continue
        if wanted != store.franchisee_id:
            plan.ops.append(DirOp("store", "franchisee", store.id, (("franchisee_id", wanted),)))


# --- Применение ------------------------------------------------------------------

_MODELS: dict[str, type] = {
    "position": Position,
    "franchisee": Franchisee,
    "department": Department,
    "store": Store,
}


@dataclass
class DirApplyReport:
    applied: list[DirOp] = field(default_factory=list)
    failed: dict[str, list[str]] = field(default_factory=dict)

    def fail(self, op: DirOp, exc: Exception) -> None:
        code = type(getattr(exc, "orig", None) or exc).__name__
        self.failed.setdefault(f"{op.kind}_{op.action}", []).append(str(op.id))
        log.warning(
            "hr_sync.directory_op_failed",
            kind=op.kind,
            action=op.action,
            id=str(op.id),
            error=code,
        )


def _temp_name(name: str, row_id: UUID) -> str:
    # Уникально по построению (полный id) и влезает в String(255).
    return f"{name[:200]} ⟳{row_id.hex}"


async def _run(db: AsyncSession, report: DirApplyReport, op: DirOp, stmt) -> bool:  # noqa: ANN001
    try:
        async with db.begin_nested():
            await db.execute(stmt)
    except DBAPIError as exc:
        report.fail(op, exc)
        return False
    return True


async def apply_directory(
    db: AsyncSession,
    tenant_id: UUID,
    ops: Iterable[DirOp],
    *,
    allowed: Callable[[DirOp], bool] = lambda op: True,
) -> DirApplyReport:
    """Применить операции плана в транзакции вызывающего, каждую — в savepoint.

    Только Core-UPDATE/INSERT без отложенных ORM-объектов: `begin_nested`
    сбрасывает всё отложенное на входе, и плохая запись вне savepoint упала бы
    на входе в следующий.
    """
    report = DirApplyReport()
    todo = sorted(
        (op for op in ops if allowed(op)),
        key=lambda op: (_ACTION_ORDER[op.action], op.kind, str(op.id)),
    )
    renames = [op for op in todo if op.action == "rename"]
    # Проход 1 переименования: временные имена освобождают все целевые.
    original_names: dict[UUID, str] = {}
    for op in renames:
        model = _MODELS[op.kind]
        current = (
            await db.execute(select(model.name).where(model.id == op.id))
        ).scalar_one_or_none()
        if current is None:
            continue
        stmt = update(model).where(model.id == op.id).values(name=_temp_name(op.get("name"), op.id))
        if await _run(db, report, op, stmt):
            original_names[op.id] = current

    for op in todo:
        model = _MODELS[op.kind]
        stmt = None
        if op.action == "archive":
            stmt = update(model).where(model.id == op.id, model.archived_at.is_(None)).values(
                archived_at=func.now()
            )
        elif op.action == "rename":
            if op.id not in original_names:
                continue
            stmt = update(model).where(model.id == op.id).values(name=op.get("name"))
        elif op.action == "update":
            changes = dict(op.values)
            if "sort_order" in changes:
                changes["position"] = changes.pop("sort_order") or 0
            if op.kind == "franchisee" and "description" in changes:
                changes["contact_info"] = changes.pop("description")
            stmt = update(model).where(model.id == op.id).values(**changes)
        elif op.action == "create":
            row: dict[str, Any] = {
                "id": op.id,
                "tenant_id": tenant_id,
                "name": op.get("name"),
                "archived_at": func.now() if op.get("archived") else None,
            }
            if op.kind == "position":
                row["description"] = op.get("description")
                row["position"] = op.get("sort_order") or 0
            elif op.kind == "franchisee":
                row["contact_info"] = op.get("description")
            stmt = pg_insert(model).values(**row).on_conflict_do_nothing(index_elements=["id"])
        elif op.action == "restore":
            stmt = update(model).where(model.id == op.id).values(archived_at=None)
        elif op.action == "reparent":
            stmt = update(model).where(model.id == op.id).values(parent_id=op.get("parent_id"))
        elif op.action == "franchisee":
            stmt = (
                update(model)
                .where(model.id == op.id)
                .values(franchisee_id=op.get("franchisee_id"))
            )
        if stmt is None:
            continue
        if await _run(db, report, op, stmt):
            report.applied.append(op)
        elif op.action == "rename":
            # Финальное имя не встало (не должно: конфликты отсекает план) —
            # возвращаем прежнее, чтобы не оставить «⟳<id>» людям на экране.
            back = update(model).where(model.id == op.id).values(name=original_names[op.id])
            await _run(db, report, op, back)
    return report
