"""Чистая арифметика «Гусиной гонки» — без I/O, под юнит-тестами.

Правила (ТЗ §3.2, решения владельца 17.09):
- позиция гуся = `100 × текущая_средняя / база`, обрезается в [0, 400];
  база = 100 клеток = стартовая линия; без базы — 100 клеток и `needs_baseline`;
- процент = `(текущая / база − 1) × 100`, один знак после запятой;
- места раздаются по клеткам (при равенстве — по проценту, средней, имени);
  точка без базы места НЕ получает (ТЗ §8.2: «на старте с пометкой»);
- общий зачёт конкурса = сумма мест по завершённым гонкам (меньше — лучше),
  пропущенная гонка = штраф `n + 1`, равенство → больше сумма финальных %;
- рекорд = закрытый день с клетками > 100 и > прежнего максимума заезда;
  первый день заезда рекордом не считается.

Все функции с датами принимают «сегодня» ЯВНО: в 22:00 UTC в Москве уже
завтра, а учётный день iiko — московская дата; `date.today()` здесь запрещён.
"""

from __future__ import annotations

import math as _math
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any, Literal
from uuid import UUID

TRACK_MAX = 400
START_CELLS = 100
# Шаг динамики: изменение меньше клетки — «без изменений».
DYNAMICS_THRESHOLD = 1

Dynamics = Literal["up", "flat", "down"]


def compute_avg(items: float, receipts: int) -> float | None:
    """Средняя наполняемость чека; нет чеков — нет средней."""
    if receipts <= 0:
        return None
    return items / receipts


def compute_cells(avg: float | None, base: float | None) -> tuple[int, bool]:
    """(клетки 0..400, needs_baseline).

    Половинки округляются вверх (`floor(x + 0.5)`), а не банковским `round`:
    место решается по показанному числу, и 150,5 у двух точек обязано давать
    одинаковый результат на любом Python.
    """
    if base is None or base <= 0 or avg is None:
        return START_CELLS, True
    raw = START_CELLS * avg / base
    cells = int(_math.floor(raw + 0.5))
    return max(0, min(TRACK_MAX, cells)), False


def compute_pct(avg: float | None, base: float | None) -> float | None:
    if base is None or base <= 0 or avg is None:
        return None
    return round((avg / base - 1) * 100, 1)


@dataclass(frozen=True)
class RankRow:
    store_id: UUID
    name: str
    cells: int
    pct: float | None
    avg: float | None
    needs_baseline: bool
    league_id: UUID | None = None
    place: int | None = None
    place_in_league: int | None = None


def _rank_key(row: RankRow) -> tuple[int, float, float, str]:
    return (-row.cells, -(row.pct or 0.0), -(row.avg or 0.0), row.name.casefold())


def rank(rows: list[RankRow]) -> list[RankRow]:
    """Раздать места: ранжируемые по убыванию клеток, без базы — в хвост без места.

    Места всегда различны (1..n): при полном равенстве решает имя, чтобы
    порядок на экране и в итогах не зависел от порядка строк из БД.
    """
    ranked = sorted((r for r in rows if not r.needs_baseline), key=_rank_key)
    tail = sorted((r for r in rows if r.needs_baseline), key=lambda r: r.name.casefold())
    out: list[RankRow] = []
    league_counter: dict[UUID, int] = {}
    for i, row in enumerate(ranked, 1):
        pil: int | None = None
        if row.league_id is not None:
            league_counter[row.league_id] = league_counter.get(row.league_id, 0) + 1
            pil = league_counter[row.league_id]
        out.append(replace(row, place=i, place_in_league=pil))
    out.extend(replace(r, place=None, place_in_league=None) for r in tail)
    return out


@dataclass(frozen=True)
class ResultRow:
    """Замороженный итог точки в одной гонке (строка `race_results`)."""

    store_id: UUID
    place: int | None
    place_in_league: int | None
    pct: float | None
    league_id: UUID | None


@dataclass(frozen=True)
class ParticipantRow:
    store_id: UUID
    name: str
    league_id: UUID | None


@dataclass(frozen=True)
class Standing:
    store_id: UUID
    name: str
    league_id: UUID | None
    place: int
    points: int
    pct_sum: float
    races_counted: int
    missed_races: int
    place_in_league: int | None
    points_in_league: int | None


def standings(
    finished: list[list[ResultRow]], participants: list[ParticipantRow]
) -> list[Standing]:
    """Общий зачёт по завершённым гонкам.

    Пропущенная гонка (точки не было или она осталась без базы) стоит
    `n + 1`, где n — число ранжированных в той гонке: иначе точка, вошедшая
    в конкурс на третьей неделе, «выигрывала» бы наименьшей суммой мест.
    Пока ни одна гонка не завершена, зачёта нет — пустой список.
    """
    if not finished:
        return []
    by_store: dict[UUID, dict[str, float]] = {
        p.store_id: {"points": 0, "pct": 0.0, "counted": 0, "missed": 0, "lpoints": 0}
        for p in participants
    }
    for race in finished:
        ranked = [r for r in race if r.place is not None]
        penalty = len(ranked) + 1
        league_sizes: dict[UUID, int] = {}
        for r in ranked:
            if r.league_id is not None and r.place_in_league is not None:
                league_sizes[r.league_id] = league_sizes.get(r.league_id, 0) + 1
        seen = {r.store_id: r for r in ranked}
        for p in participants:
            acc = by_store[p.store_id]
            row = seen.get(p.store_id)
            if row is None:
                acc["points"] += penalty
                acc["missed"] += 1
                if p.league_id is not None:
                    acc["lpoints"] += league_sizes.get(p.league_id, 0) + 1
                continue
            acc["points"] += row.place or penalty
            acc["pct"] += row.pct or 0.0
            acc["counted"] += 1
            if p.league_id is not None:
                acc["lpoints"] += row.place_in_league or (league_sizes.get(p.league_id, 0) + 1)

    def key(p: ParticipantRow) -> tuple[float, float, str]:
        acc = by_store[p.store_id]
        return (acc["points"], -acc["pct"], p.name.casefold())

    ordered = sorted(participants, key=key)
    out: list[Standing] = []
    league_place: dict[UUID, int] = {}
    for i, p in enumerate(ordered, 1):
        acc = by_store[p.store_id]
        pil: int | None = None
        lpoints: int | None = None
        if p.league_id is not None:
            league_place[p.league_id] = league_place.get(p.league_id, 0) + 1
            pil = league_place[p.league_id]
            lpoints = int(acc["lpoints"])
        out.append(
            Standing(
                store_id=p.store_id,
                name=p.name,
                league_id=p.league_id,
                place=i,
                points=int(acc["points"]),
                pct_sum=round(acc["pct"], 1),
                races_counted=int(acc["counted"]),
                missed_races=int(acc["missed"]),
                place_in_league=pil,
                points_in_league=lpoints,
            )
        )
    # Внутри лиги порядок тот же критерий, но по очкам лиги: пересчитываем
    # place_in_league отдельной сортировкой, чтобы «первый в лиге» не зависел
    # от места в общем зачёте.
    by_league: dict[UUID, list[Standing]] = {}
    for s in out:
        if s.league_id is not None:
            by_league.setdefault(s.league_id, []).append(s)
    fixed: dict[UUID, int] = {}
    for members in by_league.values():
        members.sort(key=lambda s: (s.points_in_league or 0, -s.pct_sum, s.name.casefold()))
        for j, s in enumerate(members, 1):
            fixed[s.store_id] = j
    return [replace(s, place_in_league=fixed.get(s.store_id, s.place_in_league)) for s in out]


def dynamics(live_cells: int, prev_close_cells: int | None) -> Dynamics | None:
    """Живые клетки против закрытия предыдущего дня; без снимка — неизвестно."""
    if prev_close_cells is None:
        return None
    delta = live_cells - prev_close_cells
    if delta >= DYNAMICS_THRESHOLD:
        return "up"
    if delta <= -DYNAMICS_THRESHOLD:
        return "down"
    return "flat"


def is_record(today_cells: int, prev_max_cells: int | None) -> bool:
    """Рекорд заезда: выше старта и выше прежнего максимума; первый день — нет."""
    if prev_max_cells is None:
        return False
    return today_cells > START_CELLS and today_cells > prev_max_cells


@dataclass(frozen=True)
class RaceSpan:
    seq: int
    starts_on: date
    ends_on: date


def contest_ends_on(starts_on: date, weeks_total: int) -> date:
    return starts_on + timedelta(days=weeks_total * 7 - 1)


def generate_races(starts_on: date, weeks_total: int, race_length_days: int) -> list[RaceSpan]:
    """Гонки встык от старта; число недель обязано делиться на длину заезда."""
    total_days = weeks_total * 7
    if race_length_days <= 0 or total_days % race_length_days != 0:
        raise ValueError("Число недель должно делиться на длину заезда")
    count = total_days // race_length_days
    out: list[RaceSpan] = []
    cursor = starts_on
    for seq in range(1, count + 1):
        end = cursor + timedelta(days=race_length_days - 1)
        out.append(RaceSpan(seq=seq, starts_on=cursor, ends_on=end))
        cursor = end + timedelta(days=1)
    return out


def retro_period(starts_on: date, baseline_days: int) -> tuple[date, date]:
    """Ретро-окно базы: N дней, заканчивающихся накануне старта."""
    return starts_on - timedelta(days=baseline_days), starts_on - timedelta(days=1)


def pending_snapshot_days(
    race_start: date, race_end: date, last_snapshot_day: date | None, close_day: date
) -> list[date]:
    """Дни заезда, для которых ещё нет суточного снимка, по `close_day` включительно.

    Пропущенная ночь (сбой iiko, недоступный VPS) догоняется следующей:
    функция отдаёт весь хвост, а не только `close_day`.
    """
    first = race_start if last_snapshot_day is None else last_snapshot_day + timedelta(days=1)
    last = min(race_end, close_day)
    if first > last:
        return []
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def chunk_period(date_from: date, date_to: date, max_days: int = 14) -> list[tuple[date, date]]:
    """Разбить период на окна ≤ max_days: один OLAP «подразделение × день»
    за 92 дня — это тысячи групп и таймаут без частичного прогресса."""
    if date_to < date_from:
        return []
    out: list[tuple[date, date]] = []
    cursor = date_from
    while cursor <= date_to:
        end = min(date_to, cursor + timedelta(days=max_days - 1))
        out.append((cursor, end))
        cursor = end + timedelta(days=1)
    return out


# ─── ранний старт заезда ────────────────────────────────────────────────────


def early_start_day(today: date, prev_ends_on: date, scheduled_starts_on: date) -> date | None:
    """День, с которого заезд можно начать раньше расписания, или None.

    День атомарен: два заезда не могут делить один день (оба посчитали бы одни
    и те же чеки), поэтому раньше `prev_ends_on + 1` старт невозможен — в день
    досрочного закрытия предыдущего это «завтра». Если расписание и так
    начинает заезд не позже этого дня — начинать раньше нечего.
    """
    day = max(today, prev_ends_on + timedelta(days=1))
    return day if day < scheduled_starts_on else None


def early_start_candidate(races: list[Any], today: date) -> tuple[Any, date] | None:
    """Единственный заезд, которому положена кнопка «Начать раньше», и его день.

    Активного заезда нет → первый запланированный по `seq` → его предшественник
    существует и завершён → `early_start_day`. Duck-typing (`seq`, `status`,
    `starts_on`, `ends_on`) — ради юнит-теста без ORM.
    """
    if any(r.status == "active" for r in races):
        return None
    scheduled = sorted((r for r in races if r.status == "scheduled"), key=lambda r: r.seq)
    if not scheduled:
        return None
    race = scheduled[0]
    prev = next((r for r in races if r.seq == race.seq - 1), None)
    if prev is None or prev.status != "finished":
        return None
    day = early_start_day(today, prev.ends_on, race.starts_on)
    return (race, day) if day is not None else None
