"""Audience-резолвер (Ф0 LMS): кто попадает в аудиторию и пересчёт членства.

Чистое ядро (юнит-тестируемое без БД):
- `EmployeeAttrs` — вычисленные атрибуты сотрудника;
- `RuleSpec` + `rule_matches()` — семантика одной строки правила
  (AND непустых измерений; строка без единого измерения НЕ матчит никого —
  fail-closed, создание таких include-строк запрещено валидацией);
- `audience_matches()` — семантика набора строк (include-OR, exclude
  вычитается; нет include-строк → база «все активные»).

Расширение атрибутов (ТЗ §2.1, критично):
- ТУ (org_role=tu): store_ids += закреплённые магазины из tu_store_assignments
  (+ их группы) — иначе ТУ не видит материалы «своих магазинов»;
- владелец франчайзи (franchisee_owner): store_ids += все магазины его
  франчайзи, franchisee_ids += свой франчайзи;
- франчайзи РЯДОВОГО сотрудника выводится из store.franchisee_id (не из
  профиля — protухает при переносе магазина);
- department_ids = свой отдел + все предки (материал «отделу Маркетинг»
  виден и сотрудникам под-отделов).

Конкурентность: все пересчёты берут ОДИН per-tenant advisory xact-lock
(`_lock_tenant`) — при масштабе UPPETIT (сотни сотрудников, сотни audiences)
полная сериализация пересчётов тенанта дешевле и надёжнее fine-grained
локов (нет ни deadlock-ов, ни гонок «rebuild затирает инкремент»).
Пересчёт — diff/upsert, НЕ DELETE+INSERT: granted_at существующих членов
сохраняется (от него считаются дедлайны ознакомления).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import structlog
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audience import Audience, AudienceMember, AudienceRule
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.org import (
    Department,
    FranchiseeGroupMember,
    PositionGroupMember,
    Store,
    StoreGroupMember,
    UserGroupMember,
)

log = structlog.get_logger("audience")

# --- Чистое ядро ------------------------------------------------------------


@dataclass(frozen=True)
class EmployeeAttrs:
    profile_id: UUID
    position_ids: frozenset[UUID] = frozenset()
    position_group_ids: frozenset[UUID] = frozenset()
    store_ids: frozenset[UUID] = frozenset()
    store_group_ids: frozenset[UUID] = frozenset()
    franchisee_ids: frozenset[UUID] = frozenset()
    franchisee_group_ids: frozenset[UUID] = frozenset()
    department_ids: frozenset[UUID] = frozenset()
    user_group_ids: frozenset[UUID] = frozenset()


@dataclass(frozen=True)
class RuleSpec:
    mode: str  # include | exclude
    profile_ids: frozenset[UUID] = frozenset()
    position_ids: frozenset[UUID] = frozenset()
    position_group_ids: frozenset[UUID] = frozenset()
    store_ids: frozenset[UUID] = frozenset()
    store_group_ids: frozenset[UUID] = frozenset()
    franchisee_ids: frozenset[UUID] = frozenset()
    franchisee_group_ids: frozenset[UUID] = frozenset()
    department_ids: frozenset[UUID] = frozenset()
    user_group_ids: frozenset[UUID] = frozenset()

    def is_empty(self) -> bool:
        return not (
            self.profile_ids
            or self.position_ids
            or self.position_group_ids
            or self.store_ids
            or self.store_group_ids
            or self.franchisee_ids
            or self.franchisee_group_ids
            or self.department_ids
            or self.user_group_ids
        )


# (имя измерения в RuleSpec, имя набора в EmployeeAttrs)
_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("profile_ids", "profile_id"),
    ("position_ids", "position_ids"),
    ("position_group_ids", "position_group_ids"),
    ("store_ids", "store_ids"),
    ("store_group_ids", "store_group_ids"),
    ("franchisee_ids", "franchisee_ids"),
    ("franchisee_group_ids", "franchisee_group_ids"),
    ("department_ids", "department_ids"),
    ("user_group_ids", "user_group_ids"),
)


def rule_matches(rule: RuleSpec, attrs: EmployeeAttrs) -> bool:
    """Одна строка правила: AND всех НЕПУСТЫХ измерений. Пустая строка → False."""
    if rule.is_empty():
        return False
    for rule_field, attr_field in _DIMENSIONS:
        wanted: frozenset[UUID] = getattr(rule, rule_field)
        if not wanted:
            continue
        if attr_field == "profile_id":
            if attrs.profile_id not in wanted:
                return False
        elif not (getattr(attrs, attr_field) & wanted):
            return False
    return True


def audience_matches(is_all: bool, rules: list[RuleSpec], attrs: EmployeeAttrs) -> bool:
    """Набор строк: include-OR (нет include → база «все»), exclude вычитается."""
    includes = [r for r in rules if r.mode == "include"]
    excludes = [r for r in rules if r.mode == "exclude"]
    base = is_all or not includes or any(rule_matches(r, attrs) for r in includes)
    if not base:
        return False
    return not any(rule_matches(r, attrs) for r in excludes)


def validate_rules(rules: list[RuleSpec]) -> None:
    """Include-строка без единого измерения = случайное «всем» — запрещена."""
    for rule in rules:
        if rule.mode not in ("include", "exclude"):
            raise ValueError(f"Недопустимый mode правила: {rule.mode!r}")
        if rule.mode == "include" and rule.is_empty():
            raise ValueError(
                "Include-строка должна содержать хотя бы одно условие. "
                "Для «видно всем» оставьте аудиторию пустой."
            )


def rule_spec_from_row(rule: AudienceRule) -> RuleSpec:
    return RuleSpec(
        mode=rule.mode,
        profile_ids=frozenset(rule.profile_ids or ()),
        position_ids=frozenset(rule.position_ids or ()),
        position_group_ids=frozenset(rule.position_group_ids or ()),
        store_ids=frozenset(rule.store_ids or ()),
        store_group_ids=frozenset(rule.store_group_ids or ()),
        franchisee_ids=frozenset(rule.franchisee_ids or ()),
        franchisee_group_ids=frozenset(rule.franchisee_group_ids or ()),
        department_ids=frozenset(rule.department_ids or ()),
        user_group_ids=frozenset(rule.user_group_ids or ()),
    )


def build_attrs(
    *,
    profile_id: UUID,
    org_role: str,
    position_id: UUID | None,
    store_id: UUID | None,
    department_id: UUID | None,
    profile_franchisee_id: UUID | None,
    tu_store_ids: set[UUID],
    franchisee_to_stores: dict[UUID, set[UUID]],
    store_to_franchisee: dict[UUID, UUID],
    position_to_groups: dict[UUID, set[UUID]],
    store_to_groups: dict[UUID, set[UUID]],
    franchisee_to_groups: dict[UUID, set[UUID]],
    department_parents: dict[UUID, UUID | None],
    user_group_ids: set[UUID],
) -> EmployeeAttrs:
    """Собрать атрибуты сотрудника из плоских карт справочников (pure)."""
    store_ids: set[UUID] = set()
    if store_id:
        store_ids.add(store_id)
    if org_role == "tu":
        store_ids |= tu_store_ids
    franchisee_ids: set[UUID] = set()
    if org_role == "franchisee_owner" and profile_franchisee_id:
        franchisee_ids.add(profile_franchisee_id)
        store_ids |= franchisee_to_stores.get(profile_franchisee_id, set())
    # Франчайзи рядового сотрудника — из СВОЕГО магазина (не из закреплённых
    # магазинов ТУ: материал «франчайзи X» адресован сети франчайзи, не ТУ).
    if store_id and store_id in store_to_franchisee:
        franchisee_ids.add(store_to_franchisee[store_id])

    store_group_ids: set[UUID] = set()
    for sid in store_ids:
        store_group_ids |= store_to_groups.get(sid, set())

    franchisee_group_ids: set[UUID] = set()
    for fid in franchisee_ids:
        franchisee_group_ids |= franchisee_to_groups.get(fid, set())

    department_ids: set[UUID] = set()
    dep = department_id
    seen: set[UUID] = set()
    while dep is not None and dep not in seen:
        department_ids.add(dep)
        seen.add(dep)
        dep = department_parents.get(dep)

    return EmployeeAttrs(
        profile_id=profile_id,
        position_ids=frozenset({position_id} if position_id else ()),
        position_group_ids=frozenset(
            position_to_groups.get(position_id, set()) if position_id else ()
        ),
        store_ids=frozenset(store_ids),
        store_group_ids=frozenset(store_group_ids),
        franchisee_ids=frozenset(franchisee_ids),
        franchisee_group_ids=frozenset(franchisee_group_ids),
        department_ids=frozenset(department_ids),
        user_group_ids=frozenset(user_group_ids),
    )


# --- Загрузка из БД ----------------------------------------------------------


@dataclass
class _OrgMaps:
    franchisee_to_stores: dict[UUID, set[UUID]] = field(default_factory=dict)
    store_to_franchisee: dict[UUID, UUID] = field(default_factory=dict)
    position_to_groups: dict[UUID, set[UUID]] = field(default_factory=dict)
    store_to_groups: dict[UUID, set[UUID]] = field(default_factory=dict)
    franchisee_to_groups: dict[UUID, set[UUID]] = field(default_factory=dict)
    department_parents: dict[UUID, UUID | None] = field(default_factory=dict)
    tu_assignments: dict[UUID, set[UUID]] = field(default_factory=dict)
    user_groups: dict[UUID, set[UUID]] = field(default_factory=dict)


async def _load_org_maps(db: AsyncSession) -> _OrgMaps:
    maps = _OrgMaps()
    for store_id, franchisee_id in await db.execute(
        select(Store.id, Store.franchisee_id).where(Store.archived_at.is_(None))
    ):
        if franchisee_id:
            maps.store_to_franchisee[store_id] = franchisee_id
            maps.franchisee_to_stores.setdefault(franchisee_id, set()).add(store_id)
    for position_id, group_id in await db.execute(
        select(PositionGroupMember.position_id, PositionGroupMember.group_id)
    ):
        maps.position_to_groups.setdefault(position_id, set()).add(group_id)
    for store_id, group_id in await db.execute(
        select(StoreGroupMember.store_id, StoreGroupMember.group_id)
    ):
        maps.store_to_groups.setdefault(store_id, set()).add(group_id)
    for franchisee_id, group_id in await db.execute(
        select(FranchiseeGroupMember.franchisee_id, FranchiseeGroupMember.group_id)
    ):
        maps.franchisee_to_groups.setdefault(franchisee_id, set()).add(group_id)
    for dep_id, parent_id in await db.execute(select(Department.id, Department.parent_id)):
        maps.department_parents[dep_id] = parent_id
    for profile_id, store_id in await db.execute(
        select(TuStoreAssignment.profile_id, TuStoreAssignment.store_id)
    ):
        maps.tu_assignments.setdefault(profile_id, set()).add(store_id)
    for profile_id, group_id in await db.execute(
        select(UserGroupMember.profile_id, UserGroupMember.group_id)
    ):
        maps.user_groups.setdefault(profile_id, set()).add(group_id)
    return maps


def _attrs_from_profile(profile: EmployeeProfile, maps: _OrgMaps) -> EmployeeAttrs:
    return build_attrs(
        profile_id=profile.id,
        org_role=profile.org_role,
        position_id=profile.position_id,
        store_id=profile.store_id,
        department_id=profile.department_id,
        profile_franchisee_id=profile.franchisee_id,
        tu_store_ids=maps.tu_assignments.get(profile.id, set()),
        franchisee_to_stores=maps.franchisee_to_stores,
        store_to_franchisee=maps.store_to_franchisee,
        position_to_groups=maps.position_to_groups,
        store_to_groups=maps.store_to_groups,
        franchisee_to_groups=maps.franchisee_to_groups,
        department_parents=maps.department_parents,
        user_group_ids=maps.user_groups.get(profile.id, set()),
    )


async def load_attrs_map(
    db: AsyncSession, *, profile_ids: list[UUID] | None = None
) -> dict[UUID, EmployeeAttrs]:
    """Атрибуты всех АКТИВНЫХ профилей (или только заданных) без N+1."""
    maps = await _load_org_maps(db)
    stmt = select(EmployeeProfile).where(EmployeeProfile.status == "active")
    if profile_ids is not None:
        stmt = stmt.where(EmployeeProfile.id.in_(profile_ids))
    profiles = (await db.execute(stmt)).scalars().all()
    return {p.id: _attrs_from_profile(p, maps) for p in profiles}


# --- Пересчёт членства -------------------------------------------------------


async def _lock_tenant(db: AsyncSession, tenant_id: UUID) -> None:
    """Per-tenant advisory xact-lock — сериализует все пересчёты тенанта."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"hub_audience_recalc:{tenant_id}"},
    )


@dataclass
class MembershipDiff:
    added: list[UUID] = field(default_factory=list)
    removed: list[UUID] = field(default_factory=list)


async def _apply_membership_diff(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    audience_id: UUID,
    current: set[UUID],
    desired: set[UUID],
) -> MembershipDiff:
    diff = MembershipDiff(
        added=sorted(desired - current, key=str),
        removed=sorted(current - desired, key=str),
    )
    if diff.removed:
        await db.execute(
            delete(AudienceMember).where(
                AudienceMember.audience_id == audience_id,
                AudienceMember.profile_id.in_(diff.removed),
            )
        )
    if diff.added:
        stmt = pg_insert(AudienceMember).values(
            [
                {"audience_id": audience_id, "profile_id": pid, "tenant_id": tenant_id}
                for pid in diff.added
            ]
        )
        await db.execute(
            stmt.on_conflict_do_nothing(index_elements=["audience_id", "profile_id"])
        )
    return diff


async def recalc_audience(
    db: AsyncSession,
    audience: Audience,
    *,
    attrs_map: dict[UUID, EmployeeAttrs] | None = None,
) -> MembershipDiff:
    """Пересчитать одну аудиторию по всем активным профилям (diff/upsert)."""
    await _lock_tenant(db, audience.tenant_id)
    if attrs_map is None:
        attrs_map = await load_attrs_map(db)
    rules = [
        rule_spec_from_row(r)
        for r in (
            (await db.execute(select(AudienceRule).where(AudienceRule.audience_id == audience.id)))
            .scalars()
            .all()
        )
    ]
    desired = {
        pid for pid, attrs in attrs_map.items() if audience_matches(audience.is_all, rules, attrs)
    }
    current = {
        row[0]
        for row in await db.execute(
            select(AudienceMember.profile_id).where(AudienceMember.audience_id == audience.id)
        )
    }
    diff = await _apply_membership_diff(
        db,
        tenant_id=audience.tenant_id,
        audience_id=audience.id,
        current=current,
        desired=desired,
    )
    if diff.added or diff.removed:
        log.info(
            "audience.recalc",
            audience_id=str(audience.id),
            added=len(diff.added),
            removed=len(diff.removed),
        )
    return diff


async def recalc_profile(db: AsyncSession, profile: EmployeeProfile) -> dict[UUID, MembershipDiff]:
    """Пересчитать одного сотрудника по всем аудиториям тенанта.

    Архивный профиль членства не имеет — все строки удаляются.
    """
    await _lock_tenant(db, profile.tenant_id)
    diffs: dict[UUID, MembershipDiff] = {}

    current_rows = {
        row[0]
        for row in await db.execute(
            select(AudienceMember.audience_id).where(AudienceMember.profile_id == profile.id)
        )
    }

    if profile.status != "active":
        if current_rows:
            await db.execute(
                delete(AudienceMember).where(AudienceMember.profile_id == profile.id)
            )
            for aid in current_rows:
                diffs[aid] = MembershipDiff(removed=[profile.id])
        return diffs

    attrs_map = await load_attrs_map(db, profile_ids=[profile.id])
    attrs = attrs_map.get(profile.id)
    if attrs is None:  # гонка: профиль архивирован между запросами
        return diffs

    audiences = (await db.execute(select(Audience))).scalars().all()
    rules_by_audience: dict[UUID, list[RuleSpec]] = {}
    for rule in (await db.execute(select(AudienceRule))).scalars().all():
        rules_by_audience.setdefault(rule.audience_id, []).append(rule_spec_from_row(rule))

    for audience in audiences:
        matched = audience_matches(
            audience.is_all, rules_by_audience.get(audience.id, []), attrs
        )
        has_row = audience.id in current_rows
        if matched and not has_row:
            diffs[audience.id] = await _apply_membership_diff(
                db,
                tenant_id=audience.tenant_id,
                audience_id=audience.id,
                current=set(),
                desired={profile.id},
            )
        elif not matched and has_row:
            diffs[audience.id] = await _apply_membership_diff(
                db,
                tenant_id=audience.tenant_id,
                audience_id=audience.id,
                current={profile.id},
                desired=set(),
            )
    return diffs


async def rebuild_tenant(db: AsyncSession, tenant_id: UUID) -> dict[UUID, MembershipDiff]:
    """Полный reconcile тенанта (nightly / админ-кнопка). Diff, не truncate."""
    diffs: dict[UUID, MembershipDiff] = {}
    attrs_map = await load_attrs_map(db)
    audiences = (await db.execute(select(Audience))).scalars().all()
    for audience in audiences:
        diff = await recalc_audience(db, audience, attrs_map=attrs_map)
        if diff.added or diff.removed:
            diffs[audience.id] = diff
    if diffs:
        log.warning(
            "audience.rebuild_drift",
            tenant_id=str(tenant_id),
            audiences_changed=len(diffs),
        )
    return diffs


# --- Утилиты для API ---------------------------------------------------------


async def dry_run(
    db: AsyncSession, *, is_all: bool, rules: list[RuleSpec]
) -> tuple[int, list[UUID]]:
    """Счётчик «увидят N» для AudiencePicker (без персиста). → (count, sample)."""
    validate_rules(rules)
    attrs_map = await load_attrs_map(db)
    matched = sorted(
        (pid for pid, attrs in attrs_map.items() if audience_matches(is_all, rules, attrs)),
        key=str,
    )
    return len(matched), matched[:20]


def visible_filter(model: type, profile_id: UUID):  # noqa: ANN201 — SQLAlchemy expression
    """WHERE-фрагмент видимости для списков контента (модель несёт audience_id).

    Использование (Ф1+): stmt.where(Model.status == 'published',
    visible_filter(Model, profile.id)).
    """
    from sqlalchemy import exists, or_

    return or_(
        model.audience_id.is_(None),
        exists(
            select(AudienceMember.profile_id).where(
                AudienceMember.audience_id == model.audience_id,
                AudienceMember.profile_id == profile_id,
            )
        ),
    )
