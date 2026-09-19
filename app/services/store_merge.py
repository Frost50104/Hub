"""Слияние двух карточек магазина, указывающих на ОДИН объект реестра (19.09).

Инструмент нарочно узкий: слить можно только живые карточки одного
`site_id` — четыре пары дублей, которые «сливать нельзя» было написано с
05.09, потому что данные проигравшего разбросаны по семи местам без единого
каскада. Здесь каждое место переносится явно:

| место | действие |
|---|---|
| `employee_profiles.store_id` (RESTRICT) | перенести, живые и архивные |
| `store_group_members` | перенести; где у победителя членство уже есть — удалить |
| `tu_store_assignments` | то же по `(profile_id, store_id)` |
| `shift_postings` (CASCADE!) | перенести — при будущем удалении карточки каскад унёс бы смены |
| `audience_rules.store_ids` (массив без FK) | `array_replace` + дедуп; затем `rebuild_tenant` |
| `survey_answer_sets.store_id` (снапшот без FK) | перенести: одна физическая точка — один срез |
| `race_participants` | исключённая строка проигравшего — удалить; активная — на победителя,
  его исключённая удаляется |
| `race_baselines/snapshots/results` | перенести, где у победителя нет строки с тем же
  ключом, иначе удалить |
| проигравшая карточка | `archived_at`, `site_id` остаётся (провенанс для auth и списка слияний) |

Победителя предлагает `recommend_winner` по данным (люди → участие в гонке →
возраст), решает админ. Всё — одной транзакцией, commit на вызывающем;
рассылка уведомлений новым членам аудиторий уходит после commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audience import AudienceRule
from app.models.employee_profile import EmployeeProfile, TuStoreAssignment
from app.models.org import Store, StoreGroupMember
from app.models.race import (
    RaceBaseline,
    RaceContest,
    RaceParticipant,
    RaceResult,
    RaceSnapshot,
)
from app.models.shift import ShiftPosting
from app.models.survey import SurveyAnswerSet
from app.services import audit
from app.services.audience_resolver import rebuild_tenant
from app.services.learn_notify import notify_new_audience_members

log = structlog.get_logger("store_merge")


class MergeError(ValueError):
    """409 — слить нельзя в текущем состоянии."""


@dataclass(frozen=True)
class StoreStats:
    store_id: UUID
    people: int
    race_active: bool
    created_at: datetime


def recommend_winner(a: StoreStats, b: StoreStats) -> UUID:
    """Кто остаётся: больше живых людей → участвует в гонке → старше."""
    key = lambda s: (-s.people, -int(s.race_active), s.created_at)  # noqa: E731
    return min((a, b), key=key).store_id


@dataclass
class MergeCounts:
    profiles: int = 0
    profiles_archived: int = 0
    group_members: int = 0
    group_members_dropped: int = 0
    tu: int = 0
    tu_dropped: int = 0
    shifts: int = 0
    rules: int = 0
    surveys: int = 0
    race_participants_moved: int = 0
    race_participants_dropped: int = 0
    race_rows_moved: int = 0
    race_rows_dropped: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class MergePlan:
    loser: Store
    winner: Store
    counts: MergeCounts
    recommended_winner_id: UUID


async def _count(session: AsyncSession, stmt) -> int:  # noqa: ANN001
    return int((await session.execute(stmt)).scalar_one())


async def _stats(session: AsyncSession, store: Store) -> StoreStats:
    people = await _count(
        session,
        select(func.count()).where(
            EmployeeProfile.store_id == store.id, EmployeeProfile.archived_at.is_(None)
        ),
    )
    race_active = (
        await _count(
            session,
            select(func.count())
            .select_from(RaceParticipant)
            .join(RaceContest, RaceContest.id == RaceParticipant.contest_id)
            .where(
                RaceParticipant.store_id == store.id,
                RaceParticipant.excluded_at.is_(None),
                RaceContest.status.in_(("scheduled", "active")),
            ),
        )
        > 0
    )
    return StoreStats(store.id, people, race_active, store.created_at)


async def _load_pair(session: AsyncSession, loser_id: UUID, winner_id: UUID) -> tuple[Store, Store]:
    if loser_id == winner_id:
        raise MergeError("Это одна и та же карточка")
    loser = await session.get(Store, loser_id)
    winner = await session.get(Store, winner_id)
    if loser is None or winner is None:
        raise MergeError("Карточка не найдена")
    if loser.archived_at is not None or winner.archived_at is not None:
        raise MergeError("Слить можно только живые карточки")
    if loser.site_id is None or loser.site_id != winner.site_id:
        raise MergeError("Слить можно только карточки одного объекта реестра")
    return loser, winner


async def plan_merge(session: AsyncSession, *, loser_id: UUID, winner_id: UUID) -> MergePlan:
    loser, winner = await _load_pair(session, loser_id, winner_id)
    c = MergeCounts()
    c.profiles = await _count(
        session,
        select(func.count()).where(
            EmployeeProfile.store_id == loser.id, EmployeeProfile.archived_at.is_(None)
        ),
    )
    c.profiles_archived = await _count(
        session,
        select(func.count()).where(
            EmployeeProfile.store_id == loser.id, EmployeeProfile.archived_at.is_not(None)
        ),
    )
    winner_groups = select(StoreGroupMember.group_id).where(StoreGroupMember.store_id == winner.id)
    c.group_members_dropped = await _count(
        session,
        select(func.count()).where(
            StoreGroupMember.store_id == loser.id, StoreGroupMember.group_id.in_(winner_groups)
        ),
    )
    c.group_members = (
        await _count(session, select(func.count()).where(StoreGroupMember.store_id == loser.id))
        - c.group_members_dropped
    )
    winner_tu = select(TuStoreAssignment.profile_id).where(TuStoreAssignment.store_id == winner.id)
    c.tu_dropped = await _count(
        session,
        select(func.count()).where(
            TuStoreAssignment.store_id == loser.id, TuStoreAssignment.profile_id.in_(winner_tu)
        ),
    )
    c.tu = (
        await _count(session, select(func.count()).where(TuStoreAssignment.store_id == loser.id))
        - c.tu_dropped
    )
    c.shifts = await _count(session, select(func.count()).where(ShiftPosting.store_id == loser.id))
    c.rules = await _count(
        session, select(func.count()).where(AudienceRule.store_ids.any(loser.id))
    )
    c.surveys = await _count(
        session, select(func.count()).where(SurveyAnswerSet.store_id == loser.id)
    )
    for p in (
        await session.execute(select(RaceParticipant).where(RaceParticipant.store_id == loser.id))
    ).scalars():
        twin = (
            await session.execute(
                select(RaceParticipant).where(
                    RaceParticipant.contest_id == p.contest_id,
                    RaceParticipant.store_id == winner.id,
                )
            )
        ).scalar_one_or_none()
        if twin is None or (p.excluded_at is None and twin.excluded_at is not None):
            c.race_participants_moved += 1
        else:
            c.race_participants_dropped += 1
    for model, keys in _RACE_ROWS:
        moved, dropped = await _race_rows_split(session, model, keys, loser.id, winner.id)
        c.race_rows_moved += len(moved)
        c.race_rows_dropped += len(dropped)
    recommended = recommend_winner(await _stats(session, loser), await _stats(session, winner))
    return MergePlan(loser=loser, winner=winner, counts=c, recommended_winner_id=recommended)


_RACE_ROWS = (
    (RaceBaseline, ("contest_id", "race_id")),
    (RaceSnapshot, ("race_id", "day")),
    (RaceResult, ("race_id",)),
)


async def _race_rows_split(session, model, keys, loser_id, winner_id):  # noqa: ANN001
    """Строки проигравшего: перенести, где у победителя нет строки с тем же
    ключом (иначе удалить — победитель богаче по построению)."""
    loser_rows = list(
        (await session.execute(select(model).where(model.store_id == loser_id))).scalars()
    )
    winner_keys = {
        tuple(getattr(r, k) for k in keys)
        for r in (await session.execute(select(model).where(model.store_id == winner_id))).scalars()
    }
    moved = [r for r in loser_rows if tuple(getattr(r, k) for k in keys) not in winner_keys]
    dropped = [r for r in loser_rows if tuple(getattr(r, k) for k in keys) in winner_keys]
    return moved, dropped


async def apply_merge(session: AsyncSession, plan: MergePlan, *, actor_id: UUID) -> MergeCounts:
    loser, winner, c = plan.loser, plan.winner, plan.counts
    tenant_id = loser.tenant_id
    # Сотрудники — живые и архивные (RESTRICT: без переноса архив был бы неполным).
    await session.execute(
        update(EmployeeProfile)
        .where(EmployeeProfile.store_id == loser.id)
        .values(store_id=winner.id)
    )
    winner_groups = select(StoreGroupMember.group_id).where(StoreGroupMember.store_id == winner.id)
    await session.execute(
        delete(StoreGroupMember).where(
            StoreGroupMember.store_id == loser.id, StoreGroupMember.group_id.in_(winner_groups)
        )
    )
    await session.execute(
        update(StoreGroupMember)
        .where(StoreGroupMember.store_id == loser.id)
        .values(store_id=winner.id)
    )
    winner_tu = select(TuStoreAssignment.profile_id).where(TuStoreAssignment.store_id == winner.id)
    await session.execute(
        delete(TuStoreAssignment).where(
            TuStoreAssignment.store_id == loser.id, TuStoreAssignment.profile_id.in_(winner_tu)
        )
    )
    await session.execute(
        update(TuStoreAssignment)
        .where(TuStoreAssignment.store_id == loser.id)
        .values(store_id=winner.id)
    )
    await session.execute(
        update(ShiftPosting).where(ShiftPosting.store_id == loser.id).values(store_id=winner.id)
    )
    # Массив без FK: замена + дедуп (оба id могли стоять в одном правиле).
    await session.execute(
        text(
            "UPDATE audience_rules SET store_ids = ("
            "SELECT array_agg(DISTINCT x) FROM unnest(array_replace(store_ids, :l, :w)) AS x) "
            "WHERE :l = ANY(store_ids)"
        ),
        {"l": loser.id, "w": winner.id},
    )
    await session.execute(
        update(SurveyAnswerSet)
        .where(SurveyAnswerSet.store_id == loser.id)
        .values(store_id=winner.id)
    )
    # Гонка: сначала убрать лишнюю строку, потом переписать — иначе UNIQUE.
    for p in list(
        (
            await session.execute(
                select(RaceParticipant).where(RaceParticipant.store_id == loser.id)
            )
        ).scalars()
    ):
        twin = (
            await session.execute(
                select(RaceParticipant).where(
                    RaceParticipant.contest_id == p.contest_id,
                    RaceParticipant.store_id == winner.id,
                )
            )
        ).scalar_one_or_none()
        if twin is None:
            p.store_id = winner.id
        elif p.excluded_at is None and twin.excluded_at is not None:
            await session.delete(twin)
            await session.flush()
            p.store_id = winner.id
        else:
            await session.delete(p)
        await session.flush()
    for model, keys in _RACE_ROWS:
        moved, dropped = await _race_rows_split(session, model, keys, loser.id, winner.id)
        for r in dropped:
            await session.delete(r)
        await session.flush()
        for r in moved:
            r.store_id = winner.id
        await session.flush()
    loser.archived_at = datetime.now(UTC)
    await session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="archive",
        object_type="store",
        object_id=loser.id,
        object_label=loser.name,
        diff={"merged_into": {"old": None, "new": str(winner.id)}, **_diff_counts(c)},
    )
    audit.record(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="update",
        object_type="store",
        object_id=winner.id,
        object_label=winner.name,
        diff={"merged_from": {"old": None, "new": str(loser.id)}, **_diff_counts(c)},
    )
    # Сотрудники сменили точку, правила — состав: пересчёт аудиторий всегда.
    diffs = await rebuild_tenant(session, tenant_id)
    await notify_new_audience_members(session, diffs)
    log.info(
        "store_merge.applied",
        tenant_id=str(tenant_id),
        loser=str(loser.id),
        winner=str(winner.id),
        **c.as_dict(),
    )
    return c


def _diff_counts(c: MergeCounts) -> dict[str, dict[str, int | None]]:
    return {k: {"old": None, "new": v} for k, v in c.as_dict().items() if v}
