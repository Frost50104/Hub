"""База точки: чтение эффективного значения и upsert строки `race_baselines`.

Одно правило на оба режима: эффективная база = строка `(store, race.id)`,
иначе `(store, NULL)` (на весь конкурс). Ручная правка — строка
`source='manual'`; пересчёт из iiko её не трогает без `force`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, tzinfo
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.race import RaceBaseline, RaceContest, RaceParticipant
from app.services.race.math import baseline_is_preliminary


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


async def preliminary_scopes(
    session: AsyncSession, contest_id: UUID, *, through_day: date, tz: tzinfo
) -> list[UUID | None]:
    """Scope базы (None = весь конкурс, иначе заезд), где у ЖИВОГО участника
    есть iiko-строка, посчитанная до закрытия окна, а окно уже закрыто по
    `through_day`.

    Ручные строки сюда не попадают: их никто не пересчитывает (решение
    владельца 19.09 — база новичку только вручную). Строки исключённых точек
    тоже не считаются: `compute_baselines` переписывает только участников с
    `excluded_at IS NULL`, и предварительная строка исключённой точки держала
    бы scope «предварительным» вечно — так с 05.10 по 17.10 финализация
    заново тянула 28 дней базы по всей сети каждый час (точку исключили через
    25 минут после расчёта базы). Возврат точки в состав (`set_participant`)
    снова вводит её строку в правило — и первая финализация пересчитает базу
    всем живым, включая её. Уровень конкурса идёт первым: в режиме `race` он
    фолбэк для всех заездов.
    """
    rows = (
        await session.execute(
            select(RaceBaseline.race_id, RaceBaseline.set_at, RaceBaseline.period_to)
            .join(
                RaceParticipant,
                (RaceParticipant.contest_id == RaceBaseline.contest_id)
                & (RaceParticipant.store_id == RaceBaseline.store_id),
            )
            .where(
                RaceBaseline.contest_id == contest_id,
                RaceBaseline.source == "iiko",
                RaceBaseline.period_to.is_not(None),
                RaceBaseline.period_to <= through_day,
                RaceParticipant.excluded_at.is_(None),
            )
        )
    ).all()
    scopes = {
        race_id
        for race_id, set_at, period_to in rows
        if baseline_is_preliminary(set_at, period_to, tz=tz)
    }
    return sorted(scopes, key=lambda r: (r is not None, str(r)))


async def has_iiko_baseline(session: AsyncSession, race_id: UUID) -> bool:
    """Считалась ли база заезда из iiko. Именно `iiko`, а не «любая строка»:
    ручная база одной точки, введённая до старта, не должна отменять расчёт
    для остальных (`compute_baselines` ручные и так бережёт)."""
    row = await session.execute(
        select(RaceBaseline.store_id)
        .where(RaceBaseline.race_id == race_id, RaceBaseline.source == "iiko")
        .limit(1)
    )
    return row.first() is not None
