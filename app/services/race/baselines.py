"""База точки: чтение эффективного значения и upsert строки `race_baselines`.

Одно правило на оба режима: эффективная база = строка `(store, race.id)`,
иначе `(store, NULL)` (на весь конкурс). Ручная правка — строка
`source='manual'`; пересчёт из iiko её не трогает без `force`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.race import RaceBaseline, RaceContest


@dataclass(frozen=True)
class BaselineRow:
    store_id: UUID
    race_id: UUID | None
    value: float | None
    source: str
    receipts: int | None
    items: float | None
    period_from: date | None
    period_to: date | None
    note: str | None
    set_by: UUID | None
    set_at: object


def _f(v: Decimal | float | None) -> float | None:
    return None if v is None else float(v)


def _row(b: RaceBaseline) -> BaselineRow:
    return BaselineRow(
        store_id=b.store_id,
        race_id=b.race_id,
        value=_f(b.value),
        source=b.source,
        receipts=b.receipts,
        items=_f(b.items),
        period_from=b.period_from,
        period_to=b.period_to,
        note=b.note,
        set_by=b.set_by,
        set_at=b.set_at,
    )


async def load_baselines(
    session: AsyncSession, contest: RaceContest, race_id: UUID | None
) -> dict[UUID, BaselineRow]:
    """Эффективные базы по точкам для заезда (или конкурса при race_id=None)."""
    rows = (
        await session.execute(
            select(RaceBaseline).where(
                RaceBaseline.contest_id == contest.id,
                RaceBaseline.race_id.is_(None) | (RaceBaseline.race_id == race_id),
            )
        )
    ).scalars()
    contest_level: dict[UUID, BaselineRow] = {}
    race_level: dict[UUID, BaselineRow] = {}
    for b in rows:
        (race_level if b.race_id is not None else contest_level)[b.store_id] = _row(b)
    out = dict(contest_level)
    out.update(race_level)
    return out


async def get_baseline_row(
    session: AsyncSession, contest_id: UUID, store_id: UUID, race_id: UUID | None
) -> RaceBaseline | None:
    stmt = select(RaceBaseline).where(
        RaceBaseline.contest_id == contest_id, RaceBaseline.store_id == store_id
    )
    stmt = (
        stmt.where(RaceBaseline.race_id.is_(None))
        if race_id is None
        else stmt.where(RaceBaseline.race_id == race_id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def upsert_baseline(
    session: AsyncSession,
    *,
    contest: RaceContest,
    store_id: UUID,
    race_id: UUID | None,
    value: float | None,
    source: str,
    receipts: int | None = None,
    items: float | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
    note: str | None = None,
    set_by: UUID | None = None,
) -> RaceBaseline:
    row = await get_baseline_row(session, contest.id, store_id, race_id)
    if row is None:
        row = RaceBaseline(
            tenant_id=contest.tenant_id,
            contest_id=contest.id,
            store_id=store_id,
            race_id=race_id,
            source=source,
        )
        session.add(row)
    row.value = value
    row.source = source
    row.receipts = receipts
    row.items = items
    row.period_from = period_from
    row.period_to = period_to
    row.note = note
    row.set_by = set_by
    from datetime import UTC, datetime

    row.set_at = datetime.now(UTC)
    await session.flush()
    return row
