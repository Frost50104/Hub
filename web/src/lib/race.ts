/**
 * «Гусиная гонка» — типы и клиент API. Отдельный модуль (как `lib/assistant.ts`):
 * `lib/learn.ts` тянет весь LMS-API, а этот импортируют и публичная ТВ-страница,
 * и лэйаут-код. Формулы клеток/процентов/мест считает СЕРВЕР — здесь только
 * транспорт и типы.
 */
import { api } from '@/lib/api'
import { publicApi } from '@/lib/publicApi'

export type RaceStatus = 'scheduled' | 'active' | 'finished'
export type ContestStatus = 'draft' | 'scheduled' | 'active' | 'finished' | 'cancelled'
export type BaselineMode = 'contest' | 'race'
export type Dynamics = 'up' | 'flat' | 'down'

export interface RaceLeague {
  id: string
  name: string
}

export interface RaceRef {
  id: string
  seq: number
  starts_on: string
  ends_on: string
  status: RaceStatus
  /** Мгновения границ заезда в display tz — для обратного отсчёта. */
  starts_at: string
  ends_at: string
  finish_reason?: 'schedule' | 'forced' | null
  /** День раннего старта — только в админских ответах и только у одного заезда; правило считает сервер. */
  early_start_on?: string | null
}

export interface RaceContest {
  id: string
  title: string
  status: ContestStatus
  starts_on: string
  ends_on: string
  race_length_days: number
  weeks_total: number
  baseline_mode: BaselineMode
  baseline_days: number
  leagues: RaceLeague[]
  races: RaceRef[]
}

export interface DisplayRace extends RaceRef {
  days_total: number
  day_index: number | null
  data_through: string | null
}

export interface RaceParticipant {
  store_id: string
  name: string
  code: string | null
  league_id: string | null
  cells: number
  pct: number | null
  avg: number | null
  base: number | null
  receipts: number
  items: number
  needs_baseline: boolean
  place: number | null
  place_in_league: number | null
  dynamics: Dynamics | null
  prev_close_cells: number | null
}

export interface RaceStanding {
  store_id: string
  name: string
  league_id: string | null
  place: number
  points: number
  pct_sum: number
  races_counted: number
  missed_races: number
  place_in_league: number | null
  points_in_league: number | null
  /** Точка вошла в конкурс после старта — с какого заезда (пропущенные — штраф). */
  joined_race_seq?: number | null
}

export interface FinishedRace extends RaceRef {
  winner_store_id: string | null
}

export interface RaceBoard {
  configured: boolean
  server_now: string
  contest: RaceContest | null
  race: DisplayRace | null
  participants: RaceParticipant[]
  standings: RaceStanding[]
  finished_races: FinishedRace[]
  as_of: string | null
  next_refresh_at: string | null
  poll_sec: number
  /** Нет у публичной ТВ-ручки. */
  my_store_id?: string | null
}

export interface RaceResults {
  race: RaceRef
  results: RaceParticipant[]
}

export interface RaceHistoryRow extends RaceRef {
  race_id: string
  cells: number | null
  pct: number | null
  place: number | null
  place_in_league: number | null
}

export interface RaceHistory {
  contest_id: string
  store_id: string
  races: RaceHistoryRow[]
}

export interface RaceChartPoint {
  day: string
  cells: number
  pct: number | null
  avg: number | null
  is_record: boolean
  live: boolean
}

export interface RaceChart {
  race_id: string
  store_id: string
  starts_on: string
  ends_on: string
  base: number | null
  points: RaceChartPoint[]
}

// ─── админ ──────────────────────────────────────────────────────────────────

export interface ContestDraft {
  title: string
  starts_on: string
  race_length_days: 7 | 14
  weeks_total: number
  baseline_mode: BaselineMode
  baseline_days: number
  league_group_ids: string[]
}

export interface AdminParticipant {
  store_id: string
  name: string
  code: string | null
  department_id: string
  league_id: string | null
  included: boolean
  exclude_reason: 'duplicate' | 'manual' | 'closed' | null
  department_shared_with: string[]
  joined_race_seq?: number | null
}

export interface StoreRef {
  store_id: string
  name: string
  code: string | null
}

export interface BaselineRow extends StoreRef {
  race_id: string | null
  value: number | null
  source: 'iiko' | 'manual' | null
  receipts: number | null
  items: number | null
  period_from: string | null
  period_to: string | null
  note: string | null
  set_by: string | null
  set_by_name: string | null
  set_at: string | null
  needs_baseline: boolean
}

export interface SyncState {
  last_pull_at: string | null
  last_success_at: string | null
  last_error: string | null
  last_close_day: string | null
}

export interface TvLink {
  id: string
  token: string
  url: string
  created_at: string
  revoked_at: string | null
}

export interface ContestAdmin {
  contest: RaceContest
  participants: AdminParticipant[]
  unlinked_stores: StoreRef[]
  sync: SyncState
  tv_links: TvLink[]
  sync_enabled: boolean
}

export interface ScheduleReport {
  contest: RaceContest
  races: number
  needs_baseline_store_ids: string[]
  baselines_computed: boolean
}

export interface StartReport {
  race: RaceRef
  activated: boolean
  baselines_computed: boolean
  needs_baseline_store_ids: string[]
}

export interface BaselineReport {
  period_from: string
  period_to: string
  computed: number
  skipped_manual: number
  empty: number
  pulled: boolean
}

export interface SyncReport {
  dry_run: boolean
  day_from: string
  day_to: string
  rows: number
  departments: number
  days: number
  written: boolean
  skipped_empty: boolean
}

export interface RaceSettings {
  enabled: boolean
  env_enabled: boolean
  sync_enabled: boolean
}

export const raceApi = {
  board: (): Promise<RaceBoard> => api.get<RaceBoard>('/learn/race').then((r) => r.data),
  results: (raceId: string): Promise<RaceResults> =>
    api.get<RaceResults>(`/learn/race/races/${raceId}`).then((r) => r.data),
  history: (storeId: string | null, contestId?: string | null): Promise<RaceHistory> =>
    api
      .get<RaceHistory>('/learn/race/history', {
        params: { store_id: storeId ?? undefined, contest_id: contestId ?? undefined },
      })
      .then((r) => r.data),
  chart: (raceId: string, storeId: string | null): Promise<RaceChart> =>
    api
      .get<RaceChart>(`/learn/race/races/${raceId}/chart`, {
        params: { store_id: storeId ?? undefined },
      })
      .then((r) => r.data),

  settings: (): Promise<RaceSettings> =>
    api.get<RaceSettings>('/learn/race/admin/settings').then((r) => r.data),
  setEnabled: (enabled: boolean): Promise<RaceSettings> =>
    api.put<RaceSettings>('/learn/race/admin/settings', { enabled }).then((r) => r.data),
  adminContests: (): Promise<RaceContest[]> =>
    api.get<RaceContest[]>('/learn/race/admin/contests').then((r) => r.data),
  adminContest: (id: string): Promise<ContestAdmin> =>
    api.get<ContestAdmin>(`/learn/race/admin/contests/${id}`).then((r) => r.data),
  createContest: (body: ContestDraft): Promise<ContestAdmin> =>
    api.post<ContestAdmin>('/learn/race/admin/contests', body).then((r) => r.data),
  updateContest: (id: string, body: Partial<ContestDraft>): Promise<ContestAdmin> =>
    api.patch<ContestAdmin>(`/learn/race/admin/contests/${id}`, body).then((r) => r.data),
  schedule: (id: string): Promise<ScheduleReport> =>
    api.post<ScheduleReport>(`/learn/race/admin/contests/${id}/schedule`).then((r) => r.data),
  cancel: (id: string): Promise<ContestAdmin> =>
    api.post<ContestAdmin>(`/learn/race/admin/contests/${id}/cancel`).then((r) => r.data),
  finishRace: (raceId: string): Promise<RaceResults & { pull_ok: boolean }> =>
    api
      .post<RaceResults & { pull_ok: boolean }>(`/learn/race/admin/races/${raceId}/finish`)
      .then((r) => r.data),
  startRace: (raceId: string): Promise<StartReport> =>
    api.post<StartReport>(`/learn/race/admin/races/${raceId}/start`).then((r) => r.data),
  toggleParticipant: (
    contestId: string,
    storeId: string,
    included: boolean,
  ): Promise<{ participants: AdminParticipant[]; replaced_store_id: string | null }> =>
    api
      .put<{ participants: AdminParticipant[]; replaced_store_id: string | null }>(
        `/learn/race/admin/contests/${contestId}/participants/${storeId}`,
        { included },
      )
      .then((r) => r.data),
  refreshParticipants: (contestId: string): Promise<ContestAdmin> =>
    api
      .post<ContestAdmin>(`/learn/race/admin/contests/${contestId}/participants/refresh`)
      .then((r) => r.data),
  baselines: (contestId: string, raceId: string | null): Promise<BaselineRow[]> =>
    api
      .get<BaselineRow[]>(`/learn/race/admin/contests/${contestId}/baselines`, {
        params: { race_id: raceId ?? undefined },
      })
      .then((r) => r.data),
  putBaseline: (
    contestId: string,
    storeId: string,
    body: { value: number | null; note?: string | null; race_id?: string | null },
  ): Promise<BaselineRow[]> =>
    api
      .put<BaselineRow[]>(`/learn/race/admin/contests/${contestId}/baselines/${storeId}`, body)
      .then((r) => r.data),
  recomputeBaselines: (
    contestId: string,
    body: { race_id?: string | null; force?: boolean },
  ): Promise<BaselineReport> =>
    api
      .post<BaselineReport>(`/learn/race/admin/contests/${contestId}/baselines/recompute`, body)
      .then((r) => r.data),
  sync: (body: { day_from?: string; day_to?: string } = {}, dryRun = false): Promise<SyncReport> =>
    api
      .post<SyncReport>('/learn/race/admin/sync', body, { params: { dry_run: dryRun } })
      .then((r) => r.data),
  tvLinks: (): Promise<TvLink[]> =>
    api.get<TvLink[]>('/learn/race/admin/tv-links').then((r) => r.data),
  createTvLink: (): Promise<TvLink> =>
    api.post<TvLink>('/learn/race/admin/tv-links').then((r) => r.data),
  revokeTvLink: (token: string): Promise<void> =>
    api.delete(`/learn/race/admin/tv-links/${token}`).then(() => undefined),
}

export const publicRaceApi = {
  board: (token: string): Promise<RaceBoard> =>
    publicApi.get<RaceBoard>(`/public/race/${token}`).then((r) => r.data),
}
