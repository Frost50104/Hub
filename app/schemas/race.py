"""Схемы «Гусиной гонки» (0057). Тела запросов — `extra="forbid"`: старый
бандл обязан получить 422, а не тихий no-op."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ─── общие ──────────────────────────────────────────────────────────────────


class RaceLeagueOut(BaseModel):
    id: UUID
    name: str


class RaceRefOut(BaseModel):
    id: UUID
    seq: int
    starts_on: date
    ends_on: date
    status: str
    starts_at: datetime
    ends_at: datetime
    finish_reason: str | None = None
    # День, с которого заезд можно начать раньше расписания (сегодня или
    # завтра). Заполняется ТОЛЬКО в админских ответах и только у одного
    # заезда — правило считает сервер (`math.early_start_candidate`).
    early_start_on: date | None = None


class ContestOut(BaseModel):
    id: UUID
    title: str
    status: str
    starts_on: date
    ends_on: date
    race_length_days: int
    weeks_total: int
    baseline_mode: str
    baseline_days: int
    leagues: list[RaceLeagueOut] = []
    races: list[RaceRefOut] = []


class DisplayRaceOut(RaceRefOut):
    days_total: int
    day_index: int | None = None
    data_through: date | None = None


class ParticipantOut(BaseModel):
    store_id: UUID
    name: str
    code: str | None = None
    league_id: UUID | None = None
    cells: int
    pct: float | None = None
    avg: float | None = None
    base: float | None = None
    receipts: int = 0
    items: float = 0.0
    needs_baseline: bool = False
    place: int | None = None
    place_in_league: int | None = None
    dynamics: Literal["up", "flat", "down"] | None = None
    prev_close_cells: int | None = None


class StandingOut(BaseModel):
    store_id: UUID
    name: str
    league_id: UUID | None = None
    place: int
    points: int
    pct_sum: float
    races_counted: int
    missed_races: int
    place_in_league: int | None = None
    points_in_league: int | None = None


class FinishedRaceOut(RaceRefOut):
    winner_store_id: UUID | None = None


class TvTrackResponse(BaseModel):
    """Публичная ТВ-панель: без `my_store_id`, только точки и числа."""

    configured: bool
    server_now: datetime
    contest: ContestOut | None = None
    race: DisplayRaceOut | None = None
    participants: list[ParticipantOut] = []
    standings: list[StandingOut] = []
    finished_races: list[FinishedRaceOut] = []
    as_of: datetime | None = None
    next_refresh_at: datetime | None = None
    poll_sec: int = 300


class TrackResponse(TvTrackResponse):
    my_store_id: UUID | None = None


class RaceResultsResponse(BaseModel):
    race: RaceRefOut
    results: list[ParticipantOut]


class HistoryRow(RaceRefOut):
    race_id: UUID
    cells: int | None = None
    pct: float | None = None
    place: int | None = None
    place_in_league: int | None = None


class HistoryResponse(BaseModel):
    contest_id: UUID
    store_id: UUID
    races: list[HistoryRow]


class ChartPoint(BaseModel):
    day: date
    cells: int
    pct: float | None = None
    avg: float | None = None
    is_record: bool = False
    live: bool = False


class ChartResponse(BaseModel):
    race_id: UUID
    store_id: UUID
    starts_on: date
    ends_on: date
    base: float | None = None
    points: list[ChartPoint]


# ─── админ ──────────────────────────────────────────────────────────────────


class ContestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    starts_on: date
    race_length_days: Literal[7, 14] = 7
    weeks_total: int = Field(default=4, ge=1, le=12)
    baseline_mode: Literal["contest", "race"] = "contest"
    baseline_days: int = Field(default=28, ge=7, le=92)
    league_group_ids: list[UUID] = []


class ContestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    starts_on: date | None = None
    race_length_days: Literal[7, 14] | None = None
    weeks_total: int | None = Field(default=None, ge=1, le=12)
    baseline_mode: Literal["contest", "race"] | None = None
    baseline_days: int | None = Field(default=None, ge=7, le=92)
    league_group_ids: list[UUID] | None = None


class StoreRefOut(BaseModel):
    store_id: UUID
    name: str
    code: str | None = None


class AdminParticipantOut(StoreRefOut):
    department_id: str
    league_id: UUID | None = None
    included: bool
    exclude_reason: str | None = None
    department_shared_with: list[UUID] = []


class BaselineOut(StoreRefOut):
    race_id: UUID | None = None
    value: float | None = None
    source: str | None = None
    receipts: int | None = None
    items: float | None = None
    period_from: date | None = None
    period_to: date | None = None
    note: str | None = None
    set_by: UUID | None = None
    set_by_name: str | None = None
    set_at: datetime | None = None
    needs_baseline: bool = True


class SyncStateOut(BaseModel):
    last_pull_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_close_day: date | None = None


class TvLinkOut(BaseModel):
    id: UUID
    token: UUID
    url: str
    created_at: datetime
    revoked_at: datetime | None = None


class ContestAdminOut(BaseModel):
    contest: ContestOut
    participants: list[AdminParticipantOut]
    unlinked_stores: list[StoreRefOut]
    sync: SyncStateOut
    tv_links: list[TvLinkOut]
    sync_enabled: bool


class ScheduleOut(BaseModel):
    contest: ContestOut
    races: int
    needs_baseline_store_ids: list[UUID]
    baselines_computed: bool


class ParticipantToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    included: bool


class ParticipantToggleOut(BaseModel):
    participants: list[AdminParticipantOut]
    replaced_store_id: UUID | None = None


class BaselinePut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | None = None
    note: str | None = Field(default=None, max_length=500)
    race_id: UUID | None = None


class BaselineRecompute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    race_id: UUID | None = None
    force: bool = False


class BaselineReportOut(BaseModel):
    period_from: date
    period_to: date
    computed: int
    skipped_manual: int
    empty: int
    pulled: bool


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_from: date | None = None
    day_to: date | None = None


class SyncReportOut(BaseModel):
    dry_run: bool
    day_from: date
    day_to: date
    rows: int
    departments: int
    days: int
    written: bool
    skipped_empty: bool


class FinishOut(BaseModel):
    race: RaceRefOut
    results: list[ParticipantOut]
    pull_ok: bool


class StartOut(BaseModel):
    race: RaceRefOut
    activated: bool
    baselines_computed: bool
    needs_baseline_store_ids: list[UUID]


class RaceSettingsOut(BaseModel):
    enabled: bool
    env_enabled: bool
    sync_enabled: bool


class RaceSettingsPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
