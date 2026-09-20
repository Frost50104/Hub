/**
 * Доска гонки: вид (общий забег / лига), сортировка, состояния экрана,
 * форматы чисел, страницы ТВ, URL-параметры. Чистый модуль под vitest —
 * формулы позиций и мест считает сервер, здесь только раскладка.
 */
import type { Dynamics, RaceBoard, RaceContest, RaceParticipant, RaceRef } from '@/lib/race'
import { laneOrder } from '@/lib/raceTrack'
import { NBSP, plural } from '@/lib/typography'

export const VIEW_ALL = 'all'
export const VIEW_NONE = 'none'
export type RaceView = string

export interface ViewOption {
  value: RaceView
  label: string
}

/**
 * «Общий забег» + лиги + «Вне лиг».
 *
 * Вид без единой точки не показывается (20.09): лига — снимок группы точек, и
 * пустая группа давала пустой сегмент на экране и пустую страницу в ротации ТВ
 * («Дорожка 8 из 9» без единого гуся на проде). «Вне лиг» требует СМЕШАННОГО
 * состава: если лига заведена, но ни одна точка к ней не привязана, «вне лиг»
 * — это все точки, и вид дословно повторял общий забег.
 */
export function leagueOptions(contest: RaceContest | null, participants: RaceParticipant[]): ViewOption[] {
  const out: ViewOption[] = [{ value: VIEW_ALL, label: 'Общий забег' }]
  if (!contest || contest.leagues.length === 0) return out
  for (const lg of contest.leagues) {
    if (participants.some((p) => p.league_id === lg.id)) out.push({ value: lg.id, label: lg.name })
  }
  const hasLeague = participants.some((p) => p.league_id !== null)
  if (hasLeague && participants.some((p) => p.league_id === null)) {
    out.push({ value: VIEW_NONE, label: 'Вне лиг' })
  }
  return out
}

/** Вид из URL, иначе лига моей точки, иначе общий забег. */
export function resolveView(
  param: string | null,
  contest: RaceContest | null,
  participants: RaceParticipant[],
  myStoreId: string | null | undefined,
): RaceView {
  const options = leagueOptions(contest, participants)
  if (param && options.some((o) => o.value === param)) return param
  const mine = myStoreId ? participants.find((p) => p.store_id === myStoreId) : undefined
  if (mine?.league_id && options.some((o) => o.value === mine.league_id)) return mine.league_id
  return VIEW_ALL
}

export function inView(p: RaceParticipant, view: RaceView): boolean {
  if (view === VIEW_ALL) return true
  if (view === VIEW_NONE) return p.league_id === null
  return p.league_id === view
}

/** Место для показа: в общем забеге — общее, в лиге — по лиге. */
export function displayPlace(p: RaceParticipant, view: RaceView): number | null {
  return view === VIEW_ALL || view === VIEW_NONE ? p.place : p.place_in_league
}

export interface LeaderRow {
  p: RaceParticipant
  place: number | null
}

/**
 * Строки лидеров вида: ранжированные по месту, без базы — отдельным хвостом.
 * Хвост — ТОЛЬКО по признаку базы: у ещё не начавшегося заезда места нет ни
 * у кого, и точки с базой без места остаются в основном списке (по имени),
 * иначе подпись «Без базы · N» врала бы про весь состав до старта.
 */
export function leaderboardRows(participants: RaceParticipant[], view: RaceView): {
  ranked: LeaderRow[]
  unranked: RaceParticipant[]
} {
  const rows = participants.filter((p) => inView(p, view))
  const ranked = rows
    .filter((p) => !p.needs_baseline)
    .map((p) => ({ p, place: displayPlace(p, view) }))
    .sort((a, b) => {
      if (a.place === null || b.place === null) {
        if (a.place !== b.place) return a.place === null ? 1 : -1
        return a.p.name.localeCompare(b.p.name, 'ru')
      }
      return a.place - b.place
    })
  const unranked = rows
    .filter((p) => p.needs_baseline)
    .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  return { ranked, unranked }
}

/** В общем забеге моя точка закрепляется первой дорожкой (телефон). */
export function pinMyLane<T extends { store_id: string }>(rows: T[], myStoreId: string | null | undefined): T[] {
  if (!myStoreId) return rows
  const idx = rows.findIndex((r) => r.store_id === myStoreId)
  if (idx <= 0) return rows
  const mine = rows[idx]
  if (!mine) return rows
  return [mine, ...rows.slice(0, idx), ...rows.slice(idx + 1)]
}

// ─── форматы ────────────────────────────────────────────────────────────────

const ru = (n: number, digits: number) =>
  n.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export function formatPct(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return '—'
  const sign = pct > 0 ? '+' : pct < 0 ? '−' : ''
  return `${sign}${ru(Math.abs(pct), 1)}${NBSP}%`
}

export function formatAvg(avg: number | null | undefined): string {
  if (avg === null || avg === undefined || !Number.isFinite(avg)) return '—'
  return ru(avg, 2)
}

export function formatCells(cells: number): string {
  return `${Math.round(cells)}`
}

export const DYNAMICS_LABEL: Record<Dynamics, string> = {
  up: 'растёт',
  flat: 'без изменений',
  down: 'снижается',
}

/** Цвет несёт смысл дизайн-системы: рост — green-deep, стабильность — амбер,
 *  снижение — нейтральный text2 (красный занят просрочкой и ошибками). */
export const DYNAMICS_TONE: Record<Dynamics, 'up' | 'flat' | 'down'> = { up: 'up', flat: 'flat', down: 'down' }

// ─── состояние экрана ───────────────────────────────────────────────────────

export type BoardState =
  | { kind: 'no-contest'; iikoConfigured: boolean }
  | { kind: 'scheduled'; race: RaceRef }
  | { kind: 'active'; race: RaceRef }
  | { kind: 'between'; race: RaceRef; lastFinished: RaceRef | null }
  | { kind: 'finished'; race: RaceRef | null }

export function boardState(board: RaceBoard): BoardState {
  if (!board.contest) return { kind: 'no-contest', iikoConfigured: board.configured }
  if (board.contest.status === 'finished' || board.contest.status === 'cancelled') {
    return { kind: 'finished', race: board.race }
  }
  const race = board.race
  if (!race) return { kind: 'no-contest', iikoConfigured: board.configured }
  if (race.status === 'active') return { kind: 'active', race }
  if (race.status === 'scheduled') {
    const finished = board.finished_races
    if (finished.length === 0) return { kind: 'scheduled', race }
    const last = finished.reduce<RaceRef | null>((acc, r) => (acc && acc.seq > r.seq ? acc : r), null)
    return { kind: 'between', race, lastFinished: last }
  }
  return { kind: 'finished', race }
}

/** «Обновлено 12 мин назад · следующее ~14:40»; null — данных ещё не было. */
export function freshnessLine(asOf: string | null, nextAt: string | null, now: number): string | null {
  if (!asOf) return null
  const ageMin = Math.max(0, Math.floor((now - new Date(asOf).getTime()) / 60_000))
  const age = ageMin < 1 ? 'только что' : `${plural(ageMin, 'минуту', 'минуты', 'минут')} назад`
  let next = ''
  if (nextAt) {
    const d = new Date(nextAt)
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    next = ` · следующее ~${hh}:${mm}`
  }
  return `Обновлено ${age}${next}`
}

export function laneAria(p: RaceParticipant, view: RaceView): string {
  const place = displayPlace(p, view)
  const parts = [
    [p.code, p.name].filter(Boolean).join(' '),
    p.needs_baseline ? 'база не задана' : `${formatCells(p.cells)} клеток, ${formatPct(p.pct)} к базе`,
    place ? `${place}-е место` : null,
    p.dynamics ? DYNAMICS_LABEL[p.dynamics] : null,
  ].filter(Boolean)
  return parts.join(', ')
}

// ─── ТВ ─────────────────────────────────────────────────────────────────────

export function tvPageSize(viewportH: number, laneH: number, chromeH: number): number {
  return Math.max(1, Math.floor((viewportH - chromeH) / laneH))
}

export function tvPages<T>(rows: T[], pageSize: number): T[][] {
  const size = Math.max(1, Math.floor(pageSize))
  if (rows.length === 0) return [[]]
  const out: T[][] = []
  for (let i = 0; i < rows.length; i += size) out.push(rows.slice(i, i + size))
  return out
}

export interface TvPage {
  view: RaceView
  label: string
  rows: RaceParticipant[]
}

/**
 * Страницы ротации ТВ: общий забег — все страницы, лига — только первая
 * (лидеры лиги), иначе с 63 точками и четырьмя видами цикл растягивался бы на
 * минуты. Страницы без дорожек пропускаются: `tvPages` на пустом входе отдаёт
 * `[[]]`, и вид без участников занимал 15 секунд пустым экраном. Когда
 * состава нет вовсе, остаётся ровно одна пустая страница — иначе `pages.length`
 * ноль, индекс страницы уходит в −1, а футер сообщает «Дорожка 1 из 0».
 */
export function tvRotation(
  options: ViewOption[],
  participants: RaceParticipant[],
  pageSize: number,
): TvPage[] {
  const out: TvPage[] = []
  for (const o of options) {
    const rows = laneOrder(participants.filter((p) => inView(p, o.value)))
    const chunks = tvPages(rows, pageSize)
    for (const chunk of o.value === VIEW_ALL ? chunks : chunks.slice(0, 1)) {
      if (chunk.length > 0) out.push({ view: o.value, label: o.label, rows: chunk })
    }
  }
  if (out.length === 0) return [{ view: VIEW_ALL, label: 'Общий забег', rows: [] }]
  return out
}

// ─── URL ────────────────────────────────────────────────────────────────────

export interface RaceParams {
  league: string | null
  race: string | null
  store: string | null
}

export function resolveRaceParams(params: URLSearchParams): RaceParams {
  return { league: params.get('league'), race: params.get('race'), store: params.get('store') }
}

/** Меняет только свои ключи — `tab` и чужие параметры не трогает. */
export function setRaceParams(params: URLSearchParams, patch: Partial<RaceParams>): URLSearchParams {
  const next = new URLSearchParams(params)
  for (const key of ['league', 'race', 'store'] as const) {
    if (!(key in patch)) continue
    const value = patch[key]
    if (value === null || value === undefined || value === '' || (key === 'league' && value === VIEW_ALL)) {
      next.delete(key)
    } else {
      next.set(key, value)
    }
  }
  return next
}
