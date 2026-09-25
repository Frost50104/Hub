"""Кадровые данные из auth (16d): прогон по тенанту — состояние (T1) и план/применение (T3).

Синк штата (`staff_sync`) держит строки `shadow_users` всего тенанта до своего
commit'а, а каждый запрос пользователя делает upsert своей тени — поэтому
кадровая работа идёт ОТДЕЛЬНЫМИ транзакциями, и синк штата (T2) не становится
тяжелее, чем был:

- **T1** (`write_freeze_state`) — строка `hr_sync_state`: монотонная метка
  снимка (прогон со снимком не новее обработанного пропускается) и состояние
  заморозки из ПОЛНОГО снимка справочников. Сбой, 403, 404, неполный снимок
  состояние не трогают — сбой не должен снимать заморозку.
- **T3** (`run_tenant`) — строка состояния `FOR UPDATE NOWAIT` (занято — пропуск:
  другой прогон или кнопка обхода), загрузка, чистый план (`hr_apply`,
  `org_directory_sync`), решение «применяем или только отчёт», предохранитель,
  запись по savepoint на операцию, ОДИН пакетный пересчёт членства в конце,
  пуши после commit'а.

Порядок замков в T3 — «строки → замок пересчёта», как у всех остальных
писателей (правка карточки, привязка, CSV, архив, первый вход, реестр).
Обратный порядок давал deadlock с первым входом: наш INSERT ждал бы запись
индекса почты, а вход — наш замок. `lock_timeout 10s`: занятый замок = пропуск
тика, а не зависание воркера.

Применяем, только если одновременно: тенант в `hr_apply_tenants`,
`authoritative` в снимке этого прогона, строка `authoritative`, снимок
справочников полный. Иначе — отчёт: всё то же считается, пишется только отчёт.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import tenant_scoped_session
from app.models.audience import Audience, AudienceMember, AudienceRule
from app.models.automation import AutomationJob, AutomationRule
from app.models.course import Course
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.hr_sync import HrSyncState
from app.models.library import LibraryMaterial, MaterialAcknowledgement
from app.models.progress import CourseProgress
from app.models.shadow import ShadowUser
from app.services import audit, notify_batch
from app.services.audience_resolver import (
    EmployeeAttrs,
    _load_org_maps,
    recalc_profiles,
    rule_spec_from_row,
)
from app.services.employee_profiles import archive_profile, restore_profile
from app.services.hr_apply import (
    AudienceSpec,
    Card,
    CardPlan,
    KAction,
    OrgMapsView,
    PlanContext,
    StaffRow,
    ValveDecision,
    card_attrs,
    count_new_mandatory,
    deactivation_min_age,
    fingerprint,
    matched_audiences,
    parse_staff_row,
    plan_card,
    plan_deactivation,
    resolve_targets,
)
from app.services.hr_state import tenant_applies
from app.services.learn_notify import queue_new_audience_members
from app.services.notify_batch import PushBatch
from app.services.org_directory_sync import (
    DirectoryPlan,
    DirectorySnapshot,
    apply_directory,
    load_hub_directory,
    plan_directory,
    plan_store_franchisees,
    resolve_site_map,
)

log = structlog.get_logger("hr_sync")

LOCK_TIMEOUT = "10s"


# --- T1: состояние ------------------------------------------------------------------


async def write_freeze_state(
    tenant_id: UUID, *, fetched_at: datetime, directory: DirectorySnapshot | None
) -> bool:
    """T1. → False, если более новый прогон по тенанту уже прошёл (пропустить)."""
    async with tenant_scoped_session(tenant_id) as db:
        await db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        await db.execute(
            pg_insert(HrSyncState)
            .values(tenant_id=tenant_id)
            .on_conflict_do_nothing(index_elements=["tenant_id"])
        )
        state = await db.get(
            HrSyncState, tenant_id, with_for_update=True, populate_existing=True
        )
        assert state is not None  # только что вставлена или уже была
        if state.fetched_at is not None and state.fetched_at >= fetched_at:
            return False
        now = datetime.now(UTC)
        state.fetched_at = fetched_at
        if directory is not None:
            state.in_snapshot = tenant_id in directory.tenants
            state.authoritative = directory.tenants.get(tenant_id, False)
            state.snapshot_at = fetched_at
        state.updated_at = now
        await db.commit()
    return True


# --- T3: план и применение -----------------------------------------------------------


@dataclass
class TenantRun:
    tenant_id: UUID
    tenant_slug: str | None
    fetched_at: datetime
    directory: DirectorySnapshot | None
    rows: list[dict[str, Any]]
    # employee_id карточек, которые T2 привязал в этом прогоне (требование 5).
    linked_this_run: set[UUID] = field(default_factory=set)
    # Кнопка обхода предохранителя: отпечаток показанного набора и M, которое
    # видел админ, — рост M сверх показанного отклоняется.
    override_fingerprint: str | None = None
    override_max_mandatory: int | None = None


@dataclass
class TenantResult:
    report: dict[str, Any]
    pushes: list[PushBatch] = field(default_factory=list)


class OverrideRejected(Exception):
    """Кнопка обхода: набор изменился или применять нельзя — текст для человека."""


@dataclass
class _HubState:
    cards: dict[UUID, Card]
    by_employee: dict[UUID, Card]
    active_by_email: dict[str, Card]
    archived_emails: set[str]
    maps: OrgMapsView
    live_stores: set[UUID]
    audiences: list[AudienceSpec]
    mandatory_items: dict[UUID, list[tuple[str, UUID]]]
    shadows: dict[UUID, tuple[int, datetime | None]]
    pa_rules: list[tuple[UUID, frozenset[UUID], datetime]]


def _card_from(profile: EmployeeProfile, tu: frozenset[UUID]) -> Card:
    return Card(
        id=profile.id,
        employee_id=profile.employee_id,
        email=profile.email.strip().lower(),
        full_name=profile.full_name,
        status=profile.status,
        account_kind=profile.account_kind,
        archive_reason=profile.archive_reason,
        auth_deactivated_name=profile.auth_deactivated_name,
        created_at=profile.created_at,
        hired_at=profile.hired_at,
        org_role=profile.org_role,
        position_id=profile.position_id,
        store_id=profile.store_id,
        department_id=profile.department_id,
        franchisee_id=profile.franchisee_id,
        manager_profile_id=profile.manager_profile_id,
        tu_store_ids=tu,
    )


async def _load(db: AsyncSession, row_employee_ids: list[UUID]) -> _HubState:
    tu: dict[UUID, set[UUID]] = {}
    for profile_id, store_id in await db.execute(
        select(TuStoreAssignment.profile_id, TuStoreAssignment.store_id)
    ):
        tu.setdefault(profile_id, set()).add(store_id)
    cards: dict[UUID, Card] = {}
    for profile in (await db.execute(select(EmployeeProfile))).scalars():
        cards[profile.id] = _card_from(profile, frozenset(tu.get(profile.id, ())))
    by_employee = {c.employee_id: c for c in cards.values() if c.employee_id is not None}
    active_by_email = {c.email: c for c in cards.values() if c.status == "active"}
    archived_emails = {c.email for c in cards.values() if c.status == "archived"}

    raw = await _load_org_maps(db)
    maps = OrgMapsView(
        franchisee_to_stores=raw.franchisee_to_stores,
        store_to_franchisee=raw.store_to_franchisee,
        position_to_groups=raw.position_to_groups,
        store_to_groups=raw.store_to_groups,
        franchisee_to_groups=raw.franchisee_to_groups,
        department_parents=raw.department_parents,
        user_groups=raw.user_groups,
    )
    rules: dict[UUID, list] = {}
    for rule in (await db.execute(select(AudienceRule))).scalars():
        rules.setdefault(rule.audience_id, []).append(rule_spec_from_row(rule))
    audiences = [
        AudienceSpec(a.id, a.is_all, a.is_none, tuple(rules.get(a.id, ())))
        for a in (await db.execute(select(Audience))).scalars()
    ]
    mandatory: dict[UUID, list[tuple[str, UUID]]] = {}
    for course_id, audience_id in await db.execute(
        select(Course.id, Course.audience_id).where(
            Course.status == "published",
            Course.course_type == "mandatory",
            Course.audience_id.is_not(None),
        )
    ):
        mandatory.setdefault(audience_id, []).append(("course", course_id))
    for material_id, audience_id in await db.execute(
        select(LibraryMaterial.id, LibraryMaterial.audience_id).where(
            LibraryMaterial.status == "published",
            LibraryMaterial.requires_acknowledgement.is_(True),
            LibraryMaterial.audience_id.is_not(None),
        )
    ):
        mandatory.setdefault(audience_id, []).append(("material", material_id))
    shadows: dict[UUID, tuple[int, datetime | None]] = {}
    if row_employee_ids:
        for eid, runs, since in await db.execute(
            select(
                ShadowUser.employee_id, ShadowUser.inactive_runs, ShadowUser.inactive_since
            ).where(ShadowUser.employee_id.in_(row_employee_ids))
        ):
            shadows[eid] = (runs, since)
    pa_rules = [
        (rule.id, frozenset(rule.position_ids or ()), rule.applies_from)
        for rule in (
            await db.execute(
                select(AutomationRule).where(
                    AutomationRule.enabled.is_(True),
                    AutomationRule.trigger == "position_assigned",
                )
            )
        ).scalars()
    ]
    from app.models.org import Store

    live_stores = {
        sid for (sid,) in await db.execute(select(Store.id).where(Store.archived_at.is_(None)))
    }
    return _HubState(
        cards=cards,
        by_employee=by_employee,
        active_by_email=active_by_email,
        archived_emails=archived_emails,
        maps=maps,
        live_stores=live_stores,
        audiences=audiences,
        mandatory_items=mandatory,
        shadows=shadows,
        pa_rules=pa_rules,
    )


@dataclass
class _NewCard:
    id: UUID
    row: StaffRow
    targets: dict[str, Any]
    tu: frozenset[UUID] | None


@dataclass
class _Plan:
    directory: DirectoryPlan
    cards: dict[UUID, CardPlan]
    rows_by_card: dict[UUID, StaffRow]
    new_cards: list[_NewCard]
    k_actions: list[KAction]
    skipped_rows: dict[str, list[str]]
    row_counts: dict[str, int]
    affected: set[UUID]
    counted: set[UUID]
    mandatory: int
    mandatory_new_cards: int
    position_assigned: int


def _fields_after(card: Card, plan: CardPlan | None) -> dict[str, Any]:
    fields = {
        "org_role": card.org_role,
        "position_id": card.position_id,
        "store_id": card.store_id,
        "department_id": card.department_id,
        "franchisee_id": card.franchisee_id,
    }
    if plan is not None:
        for name, (_old, new) in plan.changes.items():
            if name in fields:
                fields[name] = new
    return fields


async def _plan(
    db: AsyncSession,
    run: TenantRun,
    hub: _HubState,
    settings: Settings,
    rows: list[StaffRow],
) -> _Plan:
    now = datetime.now(UTC)
    tenant_dir, stores = await load_hub_directory(db)
    auth_dir = run.directory.for_tenant(run.tenant_id) if run.directory else None
    directory = plan_directory(auth_dir, tenant_dir) if auth_dir is not None else DirectoryPlan()
    known_franchisees = set(tenant_dir.franchisees) | _created_of(directory, "franchisee")
    site_map = resolve_site_map(stores)
    if auth_dir is not None:
        plan_store_franchisees(directory, auth_dir, stores, site_map, known_franchisees)

    skipped_rows: dict[str, list[str]] = {}
    counts = {"with_hr": 0, "not_authoritative": 0, "bad_block": 0, "mode_mismatch": 0}
    snapshot_auth = bool(run.directory and run.directory.tenants.get(run.tenant_id, False))

    # Новые карточки — id заранее: руководитель-новичок того же прогона
    # находится в карте ещё до INSERT, а ставится вторым проходом.
    new_rows: list[tuple[UUID, StaffRow]] = []
    matched: list[tuple[Card, StaffRow]] = []
    for row in rows:
        if row.hr_bad:
            counts["bad_block"] += 1
        if row.hr is None:
            continue
        counts["with_hr"] += 1
        if not row.hr.authoritative:
            counts["not_authoritative"] += 1
        elif not snapshot_auth:
            counts["mode_mismatch"] += 1
        card = hub.by_employee.get(row.employee_id)
        if card is not None:
            matched.append((card, row))
            continue
        creatable = (
            row.raw_kind in (None, "person")
            and row.role
            and row.is_active is True
            and not row.deleted
        )
        if not creatable:
            continue
        holder = hub.active_by_email.get(row.email)
        if holder is not None:
            code = "email_conflict" if holder.employee_id is not None else "link_pending"
            skipped_rows.setdefault(code, []).append(str(row.employee_id))
            continue
        if row.email in hub.archived_emails:
            skipped_rows.setdefault("archived_skip", []).append(str(row.employee_id))
            continue
        new_rows.append((uuid.uuid4(), row))

    manager_by_employee = {eid: c.id for eid, c in hub.by_employee.items()}
    manager_by_employee.update({row.employee_id: nid for nid, row in new_rows})
    ctx = PlanContext(
        site_map=site_map,
        positions=set(tenant_dir.positions) | _created_of(directory, "position"),
        departments=set(tenant_dir.departments) | _created_of(directory, "department"),
        franchisees=known_franchisees,
        manager_by_employee=manager_by_employee,
    )

    cards: dict[UUID, CardPlan] = {}
    rows_by_card: dict[UUID, StaffRow] = {}
    for card, row in matched:
        if card.account_kind != "person":
            continue  # кассы заморозку и кадровый блок не наследуют (требование 7)
        assert row.hr is not None
        plan = plan_card(
            card, row.hr, ctx, linked_this_run=row.employee_id in run.linked_this_run
        )
        cards[card.id] = plan
        rows_by_card[card.id] = row
        for code in plan.skips:
            skipped_rows.setdefault(code, []).append(str(card.id))

    new_cards: list[_NewCard] = []
    for new_id, row in new_rows:
        assert row.hr is not None
        targets, tu, skips = resolve_targets(row.hr, ctx, card_id=new_id)
        new_cards.append(_NewCard(new_id, row, targets, tu))
        for code in skips:
            skipped_rows.setdefault(code, []).append(str(new_id))

    runs_needed = settings.hr_deactivation_runs
    min_age = deactivation_min_age(runs_needed, settings.staff_sync_interval_sec)
    k_actions: list[KAction] = []
    for row in rows:
        card = hub.by_employee.get(row.employee_id)
        runs, since = hub.shadows.get(row.employee_id, (0, None))
        action = plan_deactivation(
            row,
            card,
            inactive_runs=runs,
            inactive_since=since,
            runs_needed=runs_needed,
            min_age=min_age,
            now=run.fetched_at,
            release_on_name_mismatch=settings.hr_release_on_name_mismatch,
        )
        if action is not None:
            k_actions.append(action)
    k_by_card = {a.card_id: a for a in k_actions}

    # Влияние на доступ: атрибуты до и после — по всем карточкам популяции.
    store_franchisee = {
        op.id: op.get("franchisee_id")
        for op in directory.ops
        if op.kind == "store" and op.action == "franchisee"
    }
    department_parent = {
        op.id: op.get("parent_id")
        for op in directory.ops
        if op.kind == "department" and op.action == "reparent"
    }
    maps_after = hub.maps.with_changes(
        store_franchisee=store_franchisee,
        department_parent=department_parent,
        live_stores=hub.live_stores,
    )

    def in_population_before(card: Card) -> bool:
        return card.status == "active" and card.account_kind == "person"

    def in_population_after(card: Card) -> bool:
        action = k_by_card.get(card.id)
        if action is not None and action.action == "archive":
            return False
        if action is not None and action.action == "return":
            return card.account_kind == "person"
        return in_population_before(card)

    attrs_after: dict[UUID, EmployeeAttrs] = {}
    affected: set[UUID] = set()
    for card in hub.cards.values():
        before = None
        if in_population_before(card):
            before = card_attrs(card.id, _fields_after(card, None), card.tu_store_ids, hub.maps)
        after = None
        if in_population_after(card):
            plan = cards.get(card.id)
            tu = plan.tu[1] if plan is not None and plan.tu is not None else card.tu_store_ids
            after = card_attrs(card.id, _fields_after(card, plan), tu, maps_after)
            attrs_after[card.id] = after
        if before != after:
            affected.add(card.id)
    for new in new_cards:
        fields = {
            "org_role": new.targets.get("org_role", "employee"),
            "position_id": new.targets.get("position_id"),
            "store_id": new.targets.get("store_id"),
            "department_id": new.targets.get("department_id"),
            "franchisee_id": new.targets.get("franchisee_id"),
        }
        attrs_after[new.id] = card_attrs(new.id, fields, new.tu or frozenset(), maps_after)
        affected.add(new.id)

    # Кого считает предохранитель: существующие карточки, кроме заполнения.
    fills = {cid for cid, p in cards.items() if p.outcome == "fill"}
    counted: set[UUID] = {cid for cid, p in cards.items() if p.outcome == "change"}
    counted |= {a.card_id for a in k_actions if a.action in ("archive", "return")}
    counted |= {cid for cid in affected if cid in hub.cards and cid not in fills}

    existing_affected = [cid for cid in affected if cid in hub.cards]
    current: dict[UUID, set[UUID]] = {}
    if existing_affected:
        for audience_id, profile_id in await db.execute(
            select(AudienceMember.audience_id, AudienceMember.profile_id).where(
                AudienceMember.profile_id.in_(existing_affected)
            )
        ):
            current.setdefault(profile_id, set()).add(audience_id)
    added: dict[UUID, set[UUID]] = {}
    for cid in affected:
        after_set = matched_audiences(attrs_after.get(cid), hub.audiences)
        gained = after_set - current.get(cid, set())
        if gained:
            added[cid] = gained
    done = await _done_pairs(db, set(added), hub.mandatory_items)
    mandatory = count_new_mandatory(
        {cid: a for cid, a in added.items() if cid in counted}, hub.mandatory_items, done
    )
    mandatory_new_cards = count_new_mandatory(
        {cid: a for cid, a in added.items() if cid not in counted}, hub.mandatory_items, done
    )
    position_assigned = await _position_assigned(db, hub, cards, new_cards, k_by_card, now)
    return _Plan(
        directory=directory,
        cards=cards,
        rows_by_card=rows_by_card,
        new_cards=new_cards,
        k_actions=k_actions,
        skipped_rows=skipped_rows,
        row_counts=counts,
        affected=affected,
        counted=counted,
        mandatory=mandatory,
        mandatory_new_cards=mandatory_new_cards,
        position_assigned=position_assigned,
    )


def _created_of(plan: DirectoryPlan, kind: str) -> set[UUID]:
    return {op.id for op in plan.ops if op.kind == kind and op.action == "create"}


async def _done_pairs(
    db: AsyncSession,
    profile_ids: set[UUID],
    mandatory_items: dict[UUID, list[tuple[str, UUID]]],
) -> set[tuple[str, UUID, UUID]]:
    """Пройденные курсы и подтверждённые документы — пуш таким не уходит."""
    if not profile_ids:
        return set()
    course_ids = {i for items in mandatory_items.values() for k, i in items if k == "course"}
    material_ids = {i for items in mandatory_items.values() for k, i in items if k == "material"}
    done: set[tuple[str, UUID, UUID]] = set()
    if course_ids:
        for course_id, profile_id in await db.execute(
            select(CourseProgress.course_id, CourseProgress.profile_id).where(
                CourseProgress.course_id.in_(course_ids),
                CourseProgress.profile_id.in_(profile_ids),
                CourseProgress.completed_at.is_not(None),
            )
        ):
            done.add(("course", course_id, profile_id))
    if material_ids:
        for material_id, profile_id in await db.execute(
            select(MaterialAcknowledgement.material_id, MaterialAcknowledgement.profile_id).where(
                MaterialAcknowledgement.material_id.in_(material_ids),
                MaterialAcknowledgement.profile_id.in_(profile_ids),
            )
        ):
            done.add(("material", material_id, profile_id))
    return done


async def _position_assigned(
    db: AsyncSession,
    hub: _HubState,
    cards: dict[UUID, CardPlan],
    new_cards: list[_NewCard],
    k_by_card: dict[UUID, KAction],
    now: datetime,
) -> int:
    """Сколько пар «правило position_assigned + карточка» начнут срабатывать
    из-за прогона (контракт: dry-run считает срабатывания). Правило ловит
    привязанную карточку популяции, созданную после `applies_from`, с должностью
    из списка (пустой — любая), у которой ещё нет задания по этому правилу."""
    if not hub.pa_rules:
        return 0

    def matches(position: UUID | None, positions: frozenset[UUID]) -> bool:
        return position is not None and (not positions or position in positions)

    candidates: list[tuple[UUID, UUID | None, UUID | None, datetime | None]] = []
    for cid in set(cards) | set(k_by_card):
        card = hub.cards.get(cid)
        if card is None or card.employee_id is None:
            continue  # правило ловит только привязанные карточки
        action = k_by_card.get(cid)
        if action is not None and action.action == "archive":
            continue
        returning = action is not None and action.action == "return"
        if card.status != "active" and not returning:
            continue
        before = card.position_id if card.status == "active" else None
        plan = cards.get(cid)
        after = card.position_id
        if plan is not None and "position_id" in plan.changes:
            after = plan.changes["position_id"][1]
        candidates.append((cid, before, after, card.created_at))
    for new in new_cards:
        candidates.append((new.id, None, new.targets.get("position_id"), now))
    existing = {cid for cid, *_rest in candidates}
    jobs: set[tuple[UUID, UUID]] = set()
    if existing:
        for rule_id, profile_id in await db.execute(
            select(AutomationJob.rule_id, AutomationJob.profile_id).where(
                AutomationJob.profile_id.in_(existing)
            )
        ):
            jobs.add((rule_id, profile_id))
    total = 0
    for rule_id, positions, applies_from in hub.pa_rules:
        for cid, before, after, created_at in candidates:
            if created_at is None or created_at < applies_from:
                continue
            if (rule_id, cid) in jobs or matches(before, positions):
                continue
            if matches(after, positions):
                total += 1
    return total


# --- Применение -------------------------------------------------------------------------


async def _savepoint(  # noqa: ANN201
    db: AsyncSession, failed: dict[str, list[str]], code: str, key: UUID, fn  # noqa: ANN001
) -> bool:
    try:
        async with db.begin_nested():
            await fn()
    except (DBAPIError, ValueError) as exc:
        failed.setdefault(code, []).append(str(key))
        log.warning(
            "hr_sync.op_failed",
            code=code,
            id=str(key),
            error=type(getattr(exc, "orig", None) or exc).__name__,
        )
        return False
    return True


def _str(value: Any) -> str | None:
    return None if value is None else str(value)


def _audit_diff(changes: dict[str, tuple[Any, Any]]) -> dict[str, Any]:
    return {
        name: {"old": _str(old), "new": _str(new)}
        for name, (old, new) in changes.items()
    }


async def _replace_tu(
    db: AsyncSession, tenant_id: UUID, card_id: UUID, stores: frozenset[UUID]
) -> None:
    await db.execute(delete(TuStoreAssignment).where(TuStoreAssignment.profile_id == card_id))
    if stores:
        await db.execute(
            pg_insert(TuStoreAssignment).values(
                [
                    {"tenant_id": tenant_id, "profile_id": card_id, "store_id": sid}
                    for sid in sorted(stores, key=str)
                ]
            )
        )


@dataclass
class _Applied:
    written: set[UUID] = field(default_factory=set)
    created: list[str] = field(default_factory=list)
    failed: dict[str, list[str]] = field(default_factory=dict)
    fields: dict[str, int] = field(default_factory=dict)
    k: dict[str, list[str]] = field(default_factory=dict)


async def _apply(
    db: AsyncSession,
    run: TenantRun,
    hub: _HubState,
    plan: _Plan,
    *,
    blocked: bool,
) -> _Applied:
    applied = _Applied()
    tenant_id = run.tenant_id
    created = plan.directory.created_ids()
    dir_report = await apply_directory(
        db,
        tenant_id,
        plan.directory.ops,
        allowed=(lambda op: op.id in created) if blocked else (lambda op: True),
    )
    for code, ids in dir_report.failed.items():
        applied.failed.setdefault(f"directory_{code}", []).extend(ids)

    # 1. Новые карточки — сразу с кадровыми полями (требование 5).
    inserted: dict[UUID, _NewCard] = {}
    for new in sorted(plan.new_cards, key=lambda n: str(n.id)):
        row = new.row
        values = {k: v for k, v in new.targets.items() if k != "manager_profile_id"}

        async def insert(new: _NewCard = new, row: StaffRow = row, values: dict = values) -> None:
            got = (
                await db.execute(
                    pg_insert(EmployeeProfile)
                    .values(
                        id=new.id,
                        tenant_id=tenant_id,
                        employee_id=row.employee_id,
                        email=row.email,
                        full_name=row.full_name or row.email,
                        account_kind="person",
                        **values,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["tenant_id", func.lower(EmployeeProfile.email)],
                        index_where=EmployeeProfile.status == "active",
                    )
                    .returning(EmployeeProfile.id)
                )
            ).scalar_one_or_none()
            if got is None:
                # Гонка с первым входом: карточку уже завела страница входа.
                raise ValueError("race_with_login")
            if new.tu:
                await _replace_tu(db, tenant_id, new.id, new.tu)

        if await _savepoint(db, applied.failed, "new_card", new.id, insert):
            inserted[new.id] = new
            applied.created.append(str(new.id))
            applied.written.add(new.id)
    # 2. Руководители новых — когда все новые уже есть.
    for new in inserted.values():
        manager = new.targets.get("manager_profile_id")
        if manager is None:
            continue

        async def set_manager(new: _NewCard = new, manager: UUID = manager) -> None:
            await db.execute(
                update(EmployeeProfile)
                .where(EmployeeProfile.id == new.id)
                .values(manager_profile_id=manager)
            )

        await _savepoint(db, applied.failed, "manager", new.id, set_manager)

    # 3. Существующие карточки: заполнение — всегда, изменения — если не держим.
    for card_id in sorted(plan.cards, key=str):
        card_plan = plan.cards[card_id]
        if not card_plan.touches:
            continue
        if blocked and card_plan.outcome != "fill":
            continue
        card = hub.cards[card_id]

        async def write(card_plan: CardPlan = card_plan, card: Card = card) -> None:
            if card_plan.changes:
                await db.execute(
                    update(EmployeeProfile)
                    .where(EmployeeProfile.id == card.id)
                    .values(**{name: new for name, (_old, new) in card_plan.changes.items()})
                )
            if card_plan.tu is not None:
                await _replace_tu(db, tenant_id, card.id, card_plan.tu[1])
            diff = _audit_diff(card_plan.changes)
            if card_plan.tu is not None:
                diff["tu_stores_count"] = {
                    "old": str(len(card_plan.tu[0])),
                    "new": str(len(card_plan.tu[1])),
                }
            audit.record(
                db,
                tenant_id=tenant_id,
                actor_id=None,  # инициатор — auth, а не человек в Hub
                action="update",
                object_type="employee_profile",
                object_id=card.id,
                object_label=card.full_name,
                diff=diff,
            )
            await db.flush()

        if await _savepoint(db, applied.failed, "card", card_id, write):
            applied.written.add(card_id)
            for name in card_plan.changes:
                applied.fields[name] = applied.fields.get(name, 0) + 1
            if card_plan.tu is not None:
                applied.fields["tu_stores"] = applied.fields.get("tu_stores", 0) + 1

    # 4. Правило K: архив и возврат держим вместе с изменениями; отвязка входа
    # (оживили под другим именем) — защита, применяется всегда.
    for action in sorted(plan.k_actions, key=lambda a: str(a.card_id)):
        if blocked and action.action != "release":
            continue

        async def k_write(action: KAction = action) -> None:
            profile = (
                await db.execute(
                    select(EmployeeProfile)
                    .where(EmployeeProfile.id == action.card_id)
                    .with_for_update()
                )
            ).scalar_one()
            if action.action == "archive":
                if profile.status != "active":
                    raise ValueError("not_active")
                await archive_profile(
                    db, profile, reason="auth_deactivated", actor_id=None, recalc=False
                )
                profile.auth_deactivated_name = action.name
                await db.flush()
                return
            if profile.status != "archived" or profile.archive_reason != "auth_deactivated":
                raise ValueError("not_deactivated")
            if action.action == "return":
                if action.name_mismatch:
                    # Имя в auth не совпало со снимком при архиве. После выката
                    # auth 25.09 оживить учётку другому человеку нельзя — это
                    # тот же человек с новой фамилией; возвращаем, но замечаем.
                    log.warning("hr_sync.return_name_mismatch", profile_id=str(profile.id))
                if action.email and profile.email.strip().lower() != action.email:
                    holder = (
                        await db.execute(
                            select(EmployeeProfile.id).where(
                                func.lower(EmployeeProfile.email) == action.email,
                                EmployeeProfile.status == "active",
                            )
                        )
                    ).scalar_one_or_none()
                    if holder is None:
                        profile.email = action.email
                profile.auth_deactivated_name = None
                await restore_profile(db, profile, actor_id=None, recalc=False)
                await db.flush()  # аудит восстановления — внутри этого savepoint
                return
            # release: учётку оживили под другим именем — это другой человек.
            audit.record(
                db,
                tenant_id=tenant_id,
                actor_id=None,
                action="archive",
                object_type="employee_profile",
                object_id=profile.id,
                object_label=action.name or profile.full_name,
                diff={
                    "reason": {"old": "auth_deactivated", "new": "auth_deleted"},
                    "employee_id": {"old": str(profile.employee_id), "new": None},
                },
            )
            profile.employee_id = None
            profile.archive_reason = "auth_deleted"
            if action.name:
                profile.full_name = action.name
            profile.auth_deactivated_name = None
            await db.flush()

        code = f"k_{action.action}"
        if await _savepoint(db, applied.failed, code, action.card_id, k_write):
            applied.written.add(action.card_id)
            applied.k.setdefault(action.action, []).append(str(action.card_id))
    return applied


# --- Прогон -------------------------------------------------------------------------------


def _held_items(plan: _Plan) -> list[list[Any]]:
    """Канонические операции, которые держит предохранитель, — для отпечатка."""
    created = plan.directory.created_ids()
    items: list[list[Any]] = [
        op.canonical() for op in plan.directory.ops if op.id not in created
    ]
    items += [p.canonical() for p in plan.cards.values() if p.outcome == "change"]
    items += [a.canonical() for a in plan.k_actions if a.action in ("archive", "return")]
    return items


def _pending_ops(plan: _Plan) -> dict[str, Any]:
    created = plan.directory.created_ids()
    return {
        "directory": [op.canonical() for op in plan.directory.ops if op.id not in created],
        "cards": [
            {
                "id": str(cid),
                "changes": {
                    name: [_str(old), _str(new)] for name, (old, new) in p.changes.items()
                },
                "tu": (
                    [sorted(str(x) for x in p.tu[0]), sorted(str(x) for x in p.tu[1])]
                    if p.tu is not None
                    else None
                ),
            }
            for cid, p in sorted(plan.cards.items(), key=lambda kv: str(kv[0]))
            if p.outcome == "change"
        ],
        "k": [
            {"id": str(a.card_id), "action": a.action}
            for a in plan.k_actions
            if a.action in ("archive", "return")
        ],
        "counts": {"cards": len(plan.counted), "mandatory": plan.mandatory},
    }


def _report(
    run: TenantRun,
    plan: _Plan | None,
    *,
    mode: str,
    valve: ValveDecision | None = None,
    applied: _Applied | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {"tenant_id": str(run.tenant_id), "mode": mode}
    if reason:
        report["reason"] = reason
    if plan is None:
        return report
    dir_ops: dict[str, int] = {}
    for op in plan.directory.ops:
        key = f"{op.kind}_{op.action}"
        dir_ops[key] = dir_ops.get(key, 0) + 1
    outcomes: dict[str, list[str]] = {}
    fields: dict[str, int] = {}
    for cid, p in plan.cards.items():
        if p.outcome != "none":
            outcomes.setdefault(p.outcome, []).append(str(cid))
        for name in p.changes:
            fields[name] = fields.get(name, 0) + 1
        if p.tu is not None:
            fields["tu_stores"] = fields.get("tu_stores", 0) + 1
    k: dict[str, list[str]] = {}
    for a in plan.k_actions:
        k.setdefault(a.action, []).append(str(a.card_id))
        if a.name_mismatch:
            k.setdefault("return_name_mismatch", []).append(str(a.card_id))
    report.update(
        {
            "rows": plan.row_counts,
            "directory": {
                "ops": dir_ops,
                "skips": plan.directory.skips,
                "hub_only": plan.directory.hub_only,
            },
            "cards": {key: sorted(ids) for key, ids in outcomes.items()},
            "fields": fields,
            "new_cards": sorted(str(n.id) for n in plan.new_cards),
            "skips": {code: sorted(set(ids)) for code, ids in plan.skipped_rows.items()},
            "k": k,
            "mandatory_new_members": {
                "existing": plan.mandatory,
                "new": plan.mandatory_new_cards,
            },
            "position_assigned": plan.position_assigned,
        }
    )
    if valve is not None:
        report["valve"] = {
            "cards": valve.cards,
            "mandatory": valve.mandatory,
            "max_cards": valve.max_cards,
            "max_mandatory": valve.max_mandatory,
            "tripped": valve.tripped,
        }
    if applied is not None:
        report["applied"] = {
            "created": sorted(applied.created),
            "fields": applied.fields,
            "k": applied.k,
            "failed": applied.failed,
        }
    return report


async def run_tenant(run: TenantRun, *, settings: Settings | None = None) -> TenantResult:
    """T3: план и, если можно, применение. Коммитит и отправляет пуши сам."""
    settings = settings or get_settings()
    rows = [r for r in (parse_staff_row(raw) for raw in run.rows) if r is not None]
    async with tenant_scoped_session(run.tenant_id) as db:
        await db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        await db.execute(
            pg_insert(HrSyncState)
            .values(tenant_id=run.tenant_id)
            .on_conflict_do_nothing(index_elements=["tenant_id"])
        )
        try:
            state = await db.get(
                HrSyncState,
                run.tenant_id,
                with_for_update={"nowait": True},
                populate_existing=True,
            )
            assert state is not None  # только что вставлена или уже была
        except DBAPIError:
            if run.override_fingerprint is not None:
                raise OverrideRejected(
                    "Идёт синхронизация с auth — попробуйте через минуту"
                ) from None
            return TenantResult(_report(run, None, mode="busy"))
        if state.applied_fetched_at is not None and state.applied_fetched_at >= run.fetched_at:
            return TenantResult(_report(run, None, mode="stale_snapshot"))

        now = datetime.now(UTC)
        directory_ok = run.directory is not None
        snapshot_auth = bool(run.directory and run.directory.tenants.get(run.tenant_id, False))
        applying = (
            directory_ok
            and snapshot_auth
            and state.authoritative
            and tenant_applies(run.tenant_slug, settings.hr_apply_tenant_slugs)
        )
        if run.override_fingerprint is not None and not applying:
            raise OverrideRejected(
                "Применение кадровых данных для организации сейчас выключено — "
                "набор применится сам, когда его включат"
            )
        if not directory_ok:
            report = _report(run, None, mode="skipped", reason="directory_unavailable")
            _finish_state(state, report, now=now, mode="skipped", applying=False)
            await db.commit()
            return TenantResult(report)
        if not snapshot_auth and not any(r.hr is not None for r in rows):
            # Режим NULL: auth кадровых данных тенанта не ведёт — делать нечего.
            report = _report(run, None, mode="idle")
            _finish_state(state, report, now=now, mode="idle", applying=False)
            await db.commit()
            return TenantResult(report)

        hub = await _load(db, [r.employee_id for r in rows])
        # Строки без «разрешения» применяться не будут, но в отчёт идут все.
        plan = await _plan(db, run, hub, settings, rows)
        valve = ValveDecision(
            cards=len(plan.counted),
            mandatory=plan.mandatory,
            max_cards=settings.hr_valve_max_cards,
            max_mandatory=settings.hr_valve_max_mandatory,
        )
        held = _held_items(plan)
        fp = fingerprint(held) if held else None

        if not applying:
            report = _report(run, plan, mode="report", valve=valve)
            _finish_state(state, report, now=now, mode="report", applying=False)
            await db.commit()
            log.info("hr_sync.report", **_log_fields(report))
            return TenantResult(report)

        blocked = valve.tripped
        if run.override_fingerprint is not None:
            if fp != run.override_fingerprint or fp != state.pending_fingerprint:
                raise OverrideRejected("Набор изменений изменился — откройте его снова")
            if (
                run.override_max_mandatory is not None
                and plan.mandatory > run.override_max_mandatory
            ):
                raise OverrideRejected("Набор изменений изменился — откройте его снова")
            blocked = False

        # Строки не авторитетные или при несовпадении режима не применяем.
        _drop_non_authoritative(plan, snapshot_auth)
        applied = await _apply(db, run, hub, plan, blocked=blocked)
        await db.flush()
        recalc_ids = (plan.affected | applied.written) & (
            set(hub.cards) | {UUID(x) for x in applied.created}
        )
        diffs = await recalc_profiles(db, run.tenant_id, recalc_ids)
        pushes = await queue_new_audience_members(db, diffs)

        mode = "blocked" if blocked else "apply"
        report = _report(run, plan, mode=mode, valve=valve, applied=applied)
        _finish_state(
            state,
            report,
            now=now,
            mode=mode,
            applying=True,
            fetched_at=run.fetched_at,
            pending=(fp, _pending_ops(plan), valve.reason()) if blocked else None,
        )
        if run.override_fingerprint is not None:
            audit.record(
                db,
                tenant_id=run.tenant_id,
                actor_id=None,
                action="hr_override",
                object_type="hr_sync",
                object_label="Кадровые данные из auth",
                diff={
                    "cards": {"old": None, "new": valve.cards},
                    "mandatory": {"old": None, "new": valve.mandatory},
                },
            )
        await db.commit()
    for batch in pushes:
        notify_batch.schedule_push_batch(batch)
    level = log.warning if blocked else log.info
    level("hr_sync.blocked" if blocked else "hr_sync.report", **_log_fields(report))
    return TenantResult(report, pushes)


def _drop_non_authoritative(plan: _Plan, snapshot_auth: bool) -> None:
    """Применяем только строки с `authoritative: true` при авторитетном тенанте."""
    for cid in list(plan.cards):
        block = plan.rows_by_card[cid].hr
        if block is None or not block.authoritative or not snapshot_auth:
            del plan.cards[cid]
    plan.new_cards = [
        n for n in plan.new_cards if n.row.hr is not None and n.row.hr.authoritative
    ]


def _finish_state(
    state: HrSyncState,
    report: dict[str, Any],
    *,
    now: datetime,
    mode: str,
    applying: bool,
    fetched_at: datetime | None = None,
    pending: tuple[str | None, dict[str, Any], str] | None = None,
) -> None:
    state.last_run_at = now
    state.last_mode = mode
    state.last_report = report
    if applying:
        state.applied_fetched_at = fetched_at
        state.last_applied_at = now
    if pending is not None and pending[0] is not None:
        fp, ops, reason = pending
        if state.pending_fingerprint != fp:
            state.pending_since = now
        state.pending_fingerprint = fp
        state.pending_ops = ops
        state.blocked_reason = reason
    else:
        # Чистый прогон или смена режима — отложенный набор больше не актуален.
        state.pending_fingerprint = None
        state.pending_ops = None
        state.pending_since = None
        state.blocked_reason = None
    state.updated_at = now


def _log_fields(report: dict[str, Any]) -> dict[str, Any]:
    """Лог — числа и id; вложенные словари как есть (в них нет ПДн)."""
    return {k: v for k, v in report.items() if k != "tenant_id"} | {
        "tenant": report.get("tenant_id")
    }
