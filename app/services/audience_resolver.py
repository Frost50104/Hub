"""Audience-резолвер (Ф0 LMS): кто попадает в аудиторию и пересчёт членства.

Чистое ядро (юнит-тестируемое без БД):
- `EmployeeAttrs` — вычисленные атрибуты сотрудника;
- `RuleSpec` + `rule_matches()` — семантика одной строки правила
  (AND непустых измерений; строка без единого измерения НЕ матчит никого —
  fail-closed, создание таких include-строк запрещено валидацией);
- `audience_matches()` — семантика набора строк (include-OR, exclude
  вычитается; нет include-строк → база «все активные»; `is_none` — «скрыто
  ото всех», 0051: бьёт всё, правила при этом лежат в БД как черновик).

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
from sqlalchemy import and_, delete, select, text
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
    # «Контур» профиля (employee|tu|franchisee_owner|office) — скаляр,
    # матчится membership'ом в RuleSpec.org_roles (ОС 2026-08-10).
    org_role: str = ""
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
    org_roles: frozenset[str] = frozenset()

    def is_empty(self) -> bool:
        # org_roles обязан участвовать: include-строка «весь офис» непуста.
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
            or self.org_roles
        )


# (имя измерения в RuleSpec, имя атрибута в EmployeeAttrs). Скалярные
# атрибуты (profile_id, org_role) матчатся membership'ом, наборы —
# пересечением.
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
    ("org_roles", "org_role"),
)

_SCALAR_ATTRS = ("profile_id", "org_role")


def rule_matches(rule: RuleSpec, attrs: EmployeeAttrs) -> bool:
    """Одна строка правила: AND всех НЕПУСТЫХ измерений. Пустая строка → False."""
    if rule.is_empty():
        return False
    for rule_field, attr_field in _DIMENSIONS:
        wanted: frozenset[UUID] | frozenset[str] = getattr(rule, rule_field)
        if not wanted:
            continue
        if attr_field in _SCALAR_ATTRS:
            if getattr(attrs, attr_field) not in wanted:
                return False
        elif not (getattr(attrs, attr_field) & wanted):
            return False
    return True


def audience_matches(
    is_all: bool, rules: list[RuleSpec], attrs: EmployeeAttrs, *, is_none: bool = False
) -> bool:
    """Набор строк: include-OR (нет include → база «все»), exclude вычитается.

    `is_none` («скрыто ото всех», 0051) бьёт всё: правила при этом сохраняются
    в БД как черновик, но не матчат никого. Флаг обязан доехать до КАЖДОГО
    вызова этой функции — пересчёт без него пере-добавил бы членов скрытой
    аудитории (nightly rebuild, правка карточки сотрудника).
    """
    if is_none:
        return False
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
        org_roles=frozenset(rule.org_roles or ()),
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
        org_role=org_role,
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


def learning_population_filter():  # noqa: ANN201 — SQLAlchemy expression
    """Кто вообще может учиться: активный человек, а НЕ касса точки.

    Одно определение вместо пятнадцати рукописных копий `status == "active"`
    по `app/api/`. Копии появились потому, что ветка «видно всем»
    (`audience_id IS NULL`) членство не читает вовсе и выводит популяцию
    заново — и `load_attrs_map` до неё не дотягивается. Пока условие жило в
    пятнадцати местах, исключить кассы «в одном месте» было невозможно.

    `service` — учётка кассы: общий логин на планшете, в имени адрес. Карточка
    у неё остаётся (на кассе открыт её аккаунт, решение владельца 04.09), но
    учеником она не является: ни аудиторий, ни рассылок, ни рейтинга.
    """
    return and_(
        EmployeeProfile.status == "active",
        EmployeeProfile.account_kind == "person",
    )


async def load_attrs_map(
    db: AsyncSession, *, profile_ids: list[UUID] | None = None
) -> dict[UUID, EmployeeAttrs]:
    """Атрибуты всех АКТИВНЫХ профилей (или только заданных) без N+1."""
    maps = await _load_org_maps(db)
    stmt = select(EmployeeProfile).where(learning_population_filter())
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
        pid
        for pid, attrs in attrs_map.items()
        if audience_matches(audience.is_all, rules, attrs, is_none=audience.is_none)
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

    # Касса обрабатывается как архивная — членство снимается. Без этой ветки
    # профиль, отфильтрованный в `load_attrs_map`, попадал бы ниже в проверку
    # `attrs is None` и выходил по ветке «гонка», ничего не удалив: 220 строк
    # членства повисли бы до полного пересчёта.
    if profile.status != "active" or profile.account_kind != "person":
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
            audience.is_all,
            rules_by_audience.get(audience.id, []),
            attrs,
            is_none=audience.is_none,
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
    """Полный reconcile тенанта. Diff, не truncate.

    Ночной джобы нет — юнита в `ops/systemd/` не существует. Зовут кнопка
    «Пересчитать доступы», CSV-импорт, правки оргструктуры и применение реестра.

    Замок — ДО загрузки атрибутов. `recalc_audience` берёт его и сам, но уже
    с готовой картой: атрибуты, прочитанные мимо замка, могли устареть, пока
    мы его ждали, — и пересчёт, закоммиченный в это окно (правка карточки,
    первый вход), этот rebuild молча откатывал к прочитанному. Xact-замок
    реентерабелен: повторный вызов в той же транзакции не ждёт.
    """
    await _lock_tenant(db, tenant_id)
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


# --- Управление audience контентного объекта ---------------------------------


async def set_object_audience(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    current_audience_id: UUID | None,
    is_all: bool,
    rules: list[RuleSpec],
    object_hint: str,
    is_none: bool = False,
) -> tuple[UUID | None, MembershipDiff | None]:
    """Установить/заменить аудиторию объекта.

    «Всем» (is_all без правил) = audience_id NULL — существующая audience
    удаляется. «Никому» (is_none, 0051) — audience сохраняется С правилами,
    но пересчёт вычищает членство в ноль; эта ветка обязана идти ПЕРЕД
    веткой «всем-удалить», иначе is_none поверх галки «всем» удалял бы
    аудиторию и открывал объект каждому. Иначе — reuse существующей row
    (правила заменяются) или создание новой + немедленный пересчёт членства.

    → (новый audience_id, diff пересчёта или None).
    """
    validate_rules(rules)

    # «is_all=false без правил» персистило аудиторию, означающую «все» (нет
    # include-строк → база все активные), — человек снимал галку «всем» и
    # думал, что закрыл доступ (ОС 01.09: пять таких черновиков-аттестаций).
    # Fail-closed: состояние без смысла не сохраняется. Клиентское зеркало —
    # lib/audienceHints.ts::audienceDraftProblem.
    if not is_all and not is_none and not rules:
        raise ValueError(
            "Аудитория не настроена: включите «Видно всем», "
            "добавьте правило или нажмите «Скрыть ото всех»."
        )

    if not is_none and is_all and not rules:
        if current_audience_id is not None:
            audience = await db.get(Audience, current_audience_id)
            if audience is not None:
                await db.delete(audience)  # members каскадом
        return None, None

    if current_audience_id is not None:
        audience = await db.get(Audience, current_audience_id)
    else:
        audience = None
    if audience is None:
        audience = Audience(tenant_id=tenant_id, object_hint=object_hint[:64])
        db.add(audience)
        await db.flush()

    audience.is_all = is_all
    # Явный сброс: без него однажды скрытая аудитория оставалась бы скрытой
    # после любой последующей правки правил (row переиспользуется).
    audience.is_none = is_none
    await db.execute(delete(AudienceRule).where(AudienceRule.audience_id == audience.id))
    for spec in rules:
        db.add(
            AudienceRule(
                tenant_id=tenant_id,
                audience_id=audience.id,
                mode=spec.mode,
                profile_ids=list(spec.profile_ids) or None,
                position_ids=list(spec.position_ids) or None,
                position_group_ids=list(spec.position_group_ids) or None,
                store_ids=list(spec.store_ids) or None,
                store_group_ids=list(spec.store_group_ids) or None,
                franchisee_ids=list(spec.franchisee_ids) or None,
                franchisee_group_ids=list(spec.franchisee_group_ids) or None,
                department_ids=list(spec.department_ids) or None,
                user_group_ids=list(spec.user_group_ids) or None,
                org_roles=sorted(spec.org_roles) or None,
            )
        )
    await db.flush()
    diff = await recalc_audience(db, audience)
    return audience.id, diff


async def load_audience_rules(
    db: AsyncSession, audience_id: UUID | None
) -> tuple[bool, bool, list[AudienceRule]]:
    """→ (is_all, is_none, строки правил) для отдачи фронту. NULL → (True, False, [])."""
    if audience_id is None:
        return True, False, []
    audience = await db.get(Audience, audience_id)
    if audience is None:
        return True, False, []
    rules = (
        (await db.execute(select(AudienceRule).where(AudienceRule.audience_id == audience_id)))
        .scalars()
        .all()
    )
    return audience.is_all, audience.is_none, list(rules)


# --- Утилиты для API ---------------------------------------------------------


async def dry_run(
    db: AsyncSession, *, is_all: bool, rules: list[RuleSpec], is_none: bool = False
) -> tuple[int, list[UUID]]:
    """Счётчик «увидят N» для AudiencePicker (без персиста). → (count, sample)."""
    validate_rules(rules)
    attrs_map = await load_attrs_map(db)
    matched = sorted(
        (
            pid
            for pid, attrs in attrs_map.items()
            if audience_matches(is_all, rules, attrs, is_none=is_none)
        ),
        key=str,
    )
    return len(matched), matched[:20]


# Измерения пикера: (ключ, имя поля в EmployeeAttrs). `profile_ids` сюда не
# входит — у «конкретного сотрудника» счётчик всегда 1 и смысла не несёт.
_COUNTABLE: tuple[tuple[str, str], ...] = (
    ("position_ids", "position_ids"),
    ("position_group_ids", "position_group_ids"),
    ("store_ids", "store_ids"),
    ("store_group_ids", "store_group_ids"),
    ("franchisee_ids", "franchisee_ids"),
    ("franchisee_group_ids", "franchisee_group_ids"),
    ("department_ids", "department_ids"),
    ("user_group_ids", "user_group_ids"),
    ("org_roles", "org_role"),
)


async def dimension_counts(db: AsyncSession) -> dict[str, dict[str, int]]:
    """Сколько активных сотрудников стоит за каждым значением каждого измерения.

    Пикер показывает это рядом со значением («Администратор · 0 сотрудников»):
    без числа человек выбирает должность, получает «Увидят: 0» и не понимает,
    что должность просто никому не проставлена (ОС 2026-08-24).

    Считаем ПО ТЕМ ЖЕ атрибутам, что и `dry_run` (`load_attrs_map` →
    `build_attrs`), а не `GROUP BY position_id`: у ТУ в магазины попадают
    закреплённые точки, у владельца франчайзи — вся его сеть. Наивный COUNT
    разошёлся бы со счётчиком «увидят» в том же окне.

    Ключи значений — строки (UUID приводится к str), чтобы отдать as-is в JSON.
    """
    attrs_map = await load_attrs_map(db)
    out: dict[str, dict[str, int]] = {key: {} for key, _ in _COUNTABLE}
    for attrs in attrs_map.values():
        for key, attr_field in _COUNTABLE:
            value = getattr(attrs, attr_field)
            values = (value,) if isinstance(value, str) else value
            bucket = out[key]
            for v in values:
                if not v:
                    continue
                bucket[str(v)] = bucket.get(str(v), 0) + 1
    return out


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
