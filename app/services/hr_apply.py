"""Кадровые данные из auth (16d): план по карточкам — чистые функции под юнитами.

Сюда не ходит ни БД, ни HTTP: вход — разобранные строки штата, снимок карточек
и справочников Hub, выход — план (что поменять, что пропустить и почему),
решения правила K, влияние на членства и предохранитель. Применяет план
`services/hr_sync.py`.

**Исходы для карточки** (решение владельца «новых сотрудников не считать»):
- `fill` — кадровые поля карточки в Hub пусты целиком (карточка первого входа,
  созданная синком, или legacy-карточка, которую HR не заполнил). Применяем, в
  предохранителе не считаем — это новые люди;
- `change` — расходится хоть одно поле у заполненной карточки. Считается;
- `skip_linked_empty` — карточку привязал ЭТОТ прогон, а блок `hr` пуст целиком
  (требование 5): не затираем кадровые поля, заведённые в Hub;
- `none` — совпало.

**Правило точки** — `org_directory_sync.resolve_site_map`. Точки ТУ переводятся
все или поле не трогается. Ссылка на неизвестную должность/отдел/франчайзи,
руководителя без карточки, битое значение — пропуск ПОЛЯ с кодом, остальные
поля карточки применяются.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.services.audience_resolver import EmployeeAttrs, RuleSpec, audience_matches, build_attrs
from app.services.org_directory_sync import AMBIGUOUS

ORG_ROLES = ("employee", "tu", "franchisee_owner", "office")
_REF_FIELDS = ("position_id", "department_id", "franchisee_id")
_UUID_FIELDS = ("position_id", "department_id", "franchisee_id", "site_id", "manager_employee_id")


# --- Разбор строки штата ------------------------------------------------------------


@dataclass(frozen=True)
class HrBlock:
    """Кадровый блок строки. `values` — только присланные и разобранные поля
    (ключа нет → поле не трогаем); `bad` — присланные, но битые."""

    authoritative: bool
    values: dict[str, Any]
    assigned_site_ids: tuple[UUID, ...] | None
    bad: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        """Блок «пуст целиком»: все поля пустые, контур по умолчанию."""
        for name, value in self.values.items():
            if name == "org_role":
                if value not in (None, "employee"):
                    return False
            elif value is not None:
                return False
        return not self.assigned_site_ids


@dataclass(frozen=True)
class StaffRow:
    employee_id: UUID
    email: str
    full_name: str
    role: str | None
    is_active: bool | None
    raw_kind: str | None
    deleted: bool
    hr: HrBlock | None
    hr_bad: bool = False


def _parse_uuid(value: Any) -> UUID:
    return UUID(str(value))


def parse_hr_block(raw: Any) -> HrBlock | None:
    """`hr` строки → блок; None — ключа нет или он не объект (не трогать).

    Не бросает: битое поле попадает в `bad` и не применяется, остальные — да.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("authoritative"), bool):
        return None
    values: dict[str, Any] = {}
    bad: list[str] = []
    if "hired_at" in raw:
        value = raw["hired_at"]
        if value is None:
            values["hired_at"] = None
        else:
            try:
                values["hired_at"] = date.fromisoformat(str(value))
            except ValueError:
                bad.append("hired_at")
    if "org_role" in raw:
        value = raw["org_role"]
        if value in ORG_ROLES:
            values["org_role"] = value
        else:
            # Контракт: org_role есть всегда и из четырёх. Иное уронило бы
            # CHECK — поле не трогаем, остальные применяем.
            bad.append("org_role")
    for name in _UUID_FIELDS:
        if name not in raw:
            continue
        value = raw[name]
        if value is None:
            values[name] = None
            continue
        try:
            values[name] = _parse_uuid(value)
        except ValueError:
            bad.append(name)
    assigned: tuple[UUID, ...] | None = None
    if "assigned_site_ids" in raw and raw["assigned_site_ids"] is not None:
        value = raw["assigned_site_ids"]
        try:
            if not isinstance(value, list):
                raise ValueError
            assigned = tuple(sorted({_parse_uuid(v) for v in value}, key=str))
        except ValueError:
            bad.append("assigned_site_ids")
    return HrBlock(
        authoritative=raw["authoritative"],
        values=values,
        assigned_site_ids=assigned,
        bad=tuple(bad),
    )


def parse_staff_row(row: dict[str, Any]) -> StaffRow | None:
    """Строка выгрузки штата → StaffRow; приглашения и битые строки — None."""
    if row.get("kind", "employee") != "employee":
        return None
    try:
        employee_id = _parse_uuid(row.get("employee_id"))
    except ValueError:
        return None
    email = row.get("email")
    if not isinstance(email, str) or not email:
        return None
    raw_hr = row.get("hr")
    block = parse_hr_block(raw_hr)
    is_active = row.get("is_active")
    return StaffRow(
        employee_id=employee_id,
        email=email.strip().lower(),
        full_name=(row.get("full_name") or "").strip(),
        role=row.get("role"),
        is_active=is_active if isinstance(is_active, bool) else None,
        raw_kind=row.get("account_kind"),
        deleted=bool(row.get("deleted_at")),
        hr=block,
        hr_bad=raw_hr is not None and block is None,
    )


# --- Снимок карточки Hub -------------------------------------------------------------

HR_CARD_FIELDS = (
    "hired_at",
    "org_role",
    "position_id",
    "store_id",
    "department_id",
    "franchisee_id",
    "manager_profile_id",
)


@dataclass(frozen=True)
class Card:
    id: UUID
    employee_id: UUID | None
    email: str
    full_name: str
    status: str
    account_kind: str
    archive_reason: str | None
    auth_deactivated_name: str | None
    created_at: datetime | None
    hired_at: date | None
    org_role: str
    position_id: UUID | None
    store_id: UUID | None
    department_id: UUID | None
    franchisee_id: UUID | None
    manager_profile_id: UUID | None
    tu_store_ids: frozenset[UUID] = frozenset()

    def hr_empty(self) -> bool:
        return (
            self.org_role == "employee"
            and not self.tu_store_ids
            and all(
                getattr(self, name) is None
                for name in HR_CARD_FIELDS
                if name != "org_role"
            )
        )


@dataclass
class PlanContext:
    """Что известно Hub ПОСЛЕ применения справочников этого прогона."""

    site_map: dict[UUID, UUID | str]
    positions: set[UUID]
    departments: set[UUID]
    franchisees: set[UUID]
    # employee_id → id карточки (любой статус) + запланированные новые
    manager_by_employee: dict[UUID, UUID]


# --- План карточки ---------------------------------------------------------------------


@dataclass
class CardPlan:
    card_id: UUID
    outcome: str  # fill | change | none | skip_linked_empty
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    tu: tuple[frozenset[UUID], frozenset[UUID]] | None = None
    skips: list[str] = field(default_factory=list)

    @property
    def touches(self) -> bool:
        return bool(self.changes) or self.tu is not None

    def canonical(self) -> list[Any]:
        changes = [[f, _s(old), _s(new)] for f, (old, new) in sorted(self.changes.items())]
        tu = None
        if self.tu is not None:
            tu = [sorted(str(x) for x in self.tu[0]), sorted(str(x) for x in self.tu[1])]
        return ["card", str(self.card_id), changes, tu]


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def resolve_targets(
    block: HrBlock, ctx: PlanContext, *, card_id: UUID | None = None
) -> tuple[dict[str, Any], frozenset[UUID] | None, list[str]]:
    """Блок → целевые значения полей карточки, целевой набор ТУ, коды пропусков.

    Поле, которое нельзя перевести однозначно, в целях отсутствует — его не
    трогаем (контракт: «ссылка на неизвестный id — поле не трогать»).
    """
    targets: dict[str, Any] = {}
    skips: list[str] = []
    values = block.values
    if "hired_at" in values:
        targets["hired_at"] = values["hired_at"]
    if "org_role" in values:
        targets["org_role"] = values["org_role"]
    known = {
        "position_id": ctx.positions,
        "department_id": ctx.departments,
        "franchisee_id": ctx.franchisees,
    }
    for name in _REF_FIELDS:
        if name not in values:
            continue
        ref = values[name]
        if ref is None or ref in known[name]:
            targets[name] = ref
        else:
            skips.append("unknown_ref")
    if "site_id" in values:
        site = values["site_id"]
        if site is None:
            targets["store_id"] = None
        else:
            store = ctx.site_map.get(site)
            if store is None:
                skips.append("unknown_site")
            elif store == AMBIGUOUS:
                skips.append("ambiguous_site")
            else:
                targets["store_id"] = store
    if "manager_employee_id" in values:
        manager = values["manager_employee_id"]
        if manager is None:
            targets["manager_profile_id"] = None
        else:
            manager_card = ctx.manager_by_employee.get(manager)
            if manager_card is None:
                skips.append("unknown_manager")
            elif manager_card == card_id:
                skips.append("self_manager")
            else:
                targets["manager_profile_id"] = manager_card
    tu: frozenset[UUID] | None = None
    if block.assigned_site_ids is not None:
        stores: set[UUID] = set()
        for site in block.assigned_site_ids:
            store = ctx.site_map.get(site)
            if store is None or store == AMBIGUOUS:
                skips.append("tu_partial")
                break
            stores.add(store)  # type: ignore[arg-type]
        else:
            tu = frozenset(stores)
    for name in block.bad:
        skips.append("bad_org_role" if name == "org_role" else "bad_value")
    return targets, tu, skips


def plan_card(card: Card, block: HrBlock, ctx: PlanContext, *, linked_this_run: bool) -> CardPlan:
    if linked_this_run and block.is_empty():
        return CardPlan(card.id, "skip_linked_empty")
    targets, tu_target, skips = resolve_targets(block, ctx, card_id=card.id)
    changes = {
        name: (getattr(card, name), new)
        for name, new in targets.items()
        if getattr(card, name) != new
    }
    tu = None
    if tu_target is not None and tu_target != card.tu_store_ids:
        tu = (card.tu_store_ids, tu_target)
    if not changes and tu is None:
        outcome = "none"
    elif card.hr_empty():
        outcome = "fill"
    else:
        outcome = "change"
    return CardPlan(card.id, outcome, changes, tu, skips)


# --- Правило K ---------------------------------------------------------------------------


def name_key(name: str | None) -> str:
    """Набор слов без регистра, ё = е — порядок слов не важен (как `_same_words`
    в auth: разметка переставляла «Иванова Мария» ↔ «Мария Иванова»)."""
    if not name:
        return ""
    return " ".join(sorted(name.lower().replace("ё", "е").split()))


def same_person_name(left: str | None, right: str | None) -> bool:
    key = name_key(left)
    return bool(key) and key == name_key(right)


def deactivation_min_age(runs: int, interval_sec: float) -> timedelta:
    """Минимальный срок с первого наблюдения: (K−1) интервалов минус 5 минут.
    Кнопка «Обновить из auth» и рестарты не ускоряют правило."""
    return timedelta(seconds=max(0.0, (runs - 1) * interval_sec - 300))


@dataclass(frozen=True)
class KAction:
    card_id: UUID
    action: str  # archive | return | release
    # archive: имя учётки для снимка; release: имя, которое вернуть карточке
    name: str | None = None
    # return: почта учётки (auth владеет почтой)
    email: str | None = None
    # return при несовпавшем имени (после выката auth 25.09 это тот же человек
    # с новой фамилией) — предупреждение в журнал, архив всё равно снимается.
    name_mismatch: bool = False

    def canonical(self) -> list[Any]:
        return ["k", str(self.card_id), self.action]


def plan_deactivation(
    row: StaffRow,
    card: Card | None,
    *,
    inactive_runs: int,
    inactive_since: datetime | None,
    runs_needed: int,
    min_age: timedelta,
    now: datetime,
    release_on_name_mismatch: bool = True,
) -> KAction | None:
    """Решение правила K по строке и карточке (требование 6 контракта).

    Касса правило не трогает: сырой вид строки обязан быть ровно `person`
    (`normalize_account_kind(None)` дал бы person — отсутствие признака не
    должно архивировать точку).
    """
    if card is None or row.raw_kind != "person" or card.account_kind != "person":
        return None
    if row.is_active is False:
        if (
            card.status == "active"
            and inactive_runs >= runs_needed
            and inactive_since is not None
            and inactive_since <= now - min_age
        ):
            return KAction(card.id, "archive", name=row.full_name or card.full_name)
        return None
    if (
        row.is_active is True
        and card.status == "archived"
        and card.archive_reason == "auth_deactivated"
        and card.employee_id == row.employee_id
    ):
        if same_person_name(card.auth_deactivated_name, row.full_name):
            return KAction(card.id, "return", name=row.full_name, email=row.email)
        if not release_on_name_mismatch:
            return KAction(
                card.id, "return", name=row.full_name, email=row.email, name_mismatch=True
            )
        # Учётку оживили под другим именем — это другой человек на ящике
        # уволенного (приглашение на почту отключённой учётки в auth).
        return KAction(card.id, "release", name=card.auth_deactivated_name or card.full_name)
    return None


# --- Влияние на доступ -----------------------------------------------------------------


@dataclass
class OrgMapsView:
    """Плоские карты оргструктуры — те же, что грузит `_load_org_maps`."""

    franchisee_to_stores: dict[UUID, set[UUID]]
    store_to_franchisee: dict[UUID, UUID]
    position_to_groups: dict[UUID, set[UUID]]
    store_to_groups: dict[UUID, set[UUID]]
    franchisee_to_groups: dict[UUID, set[UUID]]
    department_parents: dict[UUID, UUID | None]
    user_groups: dict[UUID, set[UUID]]

    def with_changes(
        self,
        *,
        store_franchisee: dict[UUID, UUID | None],
        department_parent: dict[UUID, UUID | None],
        live_stores: set[UUID],
    ) -> OrgMapsView:
        """Карты после справочников прогона (франчайзи точек, родители отделов)."""
        store_to_franchisee = dict(self.store_to_franchisee)
        for store_id, franchisee_id in store_franchisee.items():
            if store_id not in live_stores:
                continue  # архивные магазины в картах не участвуют
            if franchisee_id is None:
                store_to_franchisee.pop(store_id, None)
            else:
                store_to_franchisee[store_id] = franchisee_id
        franchisee_to_stores: dict[UUID, set[UUID]] = {}
        for store_id, franchisee_id in store_to_franchisee.items():
            franchisee_to_stores.setdefault(franchisee_id, set()).add(store_id)
        department_parents = dict(self.department_parents)
        department_parents.update(department_parent)
        return OrgMapsView(
            franchisee_to_stores=franchisee_to_stores,
            store_to_franchisee=store_to_franchisee,
            position_to_groups=self.position_to_groups,
            store_to_groups=self.store_to_groups,
            franchisee_to_groups=self.franchisee_to_groups,
            department_parents=department_parents,
            user_groups=self.user_groups,
        )


def card_attrs(
    card_id: UUID, fields: dict[str, Any], tu: frozenset[UUID], maps: OrgMapsView
) -> EmployeeAttrs:
    return build_attrs(
        profile_id=card_id,
        org_role=fields["org_role"],
        position_id=fields["position_id"],
        store_id=fields["store_id"],
        department_id=fields["department_id"],
        profile_franchisee_id=fields["franchisee_id"],
        tu_store_ids=set(tu),
        franchisee_to_stores=maps.franchisee_to_stores,
        store_to_franchisee=maps.store_to_franchisee,
        position_to_groups=maps.position_to_groups,
        store_to_groups=maps.store_to_groups,
        franchisee_to_groups=maps.franchisee_to_groups,
        department_parents=maps.department_parents,
        user_group_ids=maps.user_groups.get(card_id, set()),
    )


@dataclass(frozen=True)
class AudienceSpec:
    id: UUID
    is_all: bool
    is_none: bool
    rules: tuple[RuleSpec, ...]


def matched_audiences(attrs: EmployeeAttrs | None, audiences: Iterable[AudienceSpec]) -> set[UUID]:
    if attrs is None:
        return set()
    return {
        a.id
        for a in audiences
        if audience_matches(a.is_all, list(a.rules), attrs, is_none=a.is_none)
    }


def count_new_mandatory(
    added: dict[UUID, set[UUID]],
    mandatory_items: dict[UUID, list[tuple[str, UUID]]],
    done: set[tuple[str, UUID, UUID]],
) -> int:
    """Новые членства с обязательным контентом: пара (аудитория, карточка),
    где в аудитории есть опубликованный обязательный курс или документ на
    ознакомление, ещё не пройденный этой карточкой, — ровно те, кому
    `notify_new_audience_members` отправил бы пуш."""
    total = 0
    for profile_id, audiences in added.items():
        for audience_id in audiences:
            items = mandatory_items.get(audience_id, ())
            if any((kind, item_id, profile_id) not in done for kind, item_id in items):
                total += 1
    return total


# --- Предохранитель и отпечаток -----------------------------------------------------------


@dataclass(frozen=True)
class ValveDecision:
    cards: int
    mandatory: int
    max_cards: int
    max_mandatory: int

    @property
    def tripped(self) -> bool:
        return self.cards > self.max_cards or self.mandatory > self.max_mandatory

    def reason(self) -> str:
        parts = []
        if self.cards > self.max_cards:
            parts.append(f"карточек {self.cards} > {self.max_cards}")
        if self.mandatory > self.max_mandatory:
            parts.append(f"обязательных членств {self.mandatory} > {self.max_mandatory}")
        return "; ".join(parts)


def fingerprint(items: Iterable[list[Any]]) -> str:
    """sha256 отсортированных канонических операций — «ровно этот набор»."""
    canon = sorted(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items)
    return hashlib.sha256("\n".join(canon).encode()).hexdigest()
