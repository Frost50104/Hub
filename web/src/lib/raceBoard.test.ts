import { describe, expect, it } from 'vitest'

import type { RaceBoard, RaceContest, RaceParticipant, RaceRef } from './race'
import {
  boardState,
  formatAvg,
  formatPct,
  freshnessLine,
  laneAria,
  leaderboardRows,
  leagueOptions,
  pinMyLane,
  resolveRaceParams,
  resolveView,
  setRaceParams,
  tvPages,
  tvPageSize,
} from './raceBoard'
import { NBSP } from './typography'

const race = (over: Partial<RaceRef> = {}): RaceRef => ({
  id: 'r1',
  seq: 1,
  starts_on: '2026-09-21',
  ends_on: '2026-09-27',
  status: 'active',
  starts_at: '2026-09-21T00:00:00+03:00',
  ends_at: '2026-09-28T00:00:00+03:00',
  ...over,
})

const contest = (over: Partial<RaceContest> = {}): RaceContest => ({
  id: 'c1',
  title: 'Осень',
  status: 'active',
  starts_on: '2026-09-21',
  ends_on: '2026-10-18',
  race_length_days: 7,
  weeks_total: 4,
  baseline_mode: 'contest',
  baseline_days: 28,
  leagues: [
    { id: 'L1', name: 'Центр' },
    { id: 'L2', name: 'Область' },
  ],
  races: [race()],
  ...over,
})

const p = (over: Partial<RaceParticipant>): RaceParticipant => ({
  store_id: over.name ?? 'x',
  name: 'Точка',
  code: null,
  league_id: null,
  cells: 100,
  pct: 0,
  avg: 2,
  base: 2,
  receipts: 10,
  items: 20,
  needs_baseline: false,
  place: null,
  place_in_league: null,
  dynamics: null,
  prev_close_cells: null,
  ...over,
})

const board = (over: Partial<RaceBoard> = {}): RaceBoard => ({
  configured: true,
  server_now: '2026-09-24T10:00:00Z',
  contest: contest(),
  race: { ...race(), days_total: 7, day_index: 4, data_through: '2026-09-24' },
  participants: [],
  standings: [],
  finished_races: [],
  as_of: null,
  next_refresh_at: null,
  poll_sec: 300,
  my_store_id: null,
  ...over,
})

describe('вид доски', () => {
  const parts = [
    p({ name: 'А', league_id: 'L1', place: 1, place_in_league: 1, cells: 300 }),
    p({ name: 'Б', league_id: 'L2', place: 2, place_in_league: 1, cells: 250 }),
    p({ name: 'В', league_id: 'L1', place: 3, place_in_league: 2, cells: 200 }),
    p({ name: 'Г', league_id: null, place: 4, cells: 150 }),
    p({ name: 'Д', league_id: 'L1', needs_baseline: true, place: null }),
  ]

  it('опции: общий забег, лиги и «Вне лиг» только когда есть точки без лиги', () => {
    expect(leagueOptions(contest(), parts).map((o) => o.value)).toEqual(['all', 'L1', 'L2', 'none'])
    expect(leagueOptions(contest({ leagues: [] }), parts).map((o) => o.value)).toEqual(['all'])
    expect(leagueOptions(contest(), parts.filter((x) => x.league_id)).map((o) => o.value)).toEqual(['all', 'L1', 'L2'])
  })

  it('вид по умолчанию — лига моей точки, неизвестный параметр — общий забег', () => {
    expect(resolveView(null, contest(), parts, 'Б')).toBe('L2')
    expect(resolveView(null, contest(), parts, 'Г')).toBe('all')
    expect(resolveView('L1', contest(), parts, 'Б')).toBe('L1')
    expect(resolveView('unknown', contest(), parts, null)).toBe('all')
  })

  it('в общем забеге место общее, в лиге — по лиге, без базы — в хвост', () => {
    const all = leaderboardRows(parts, 'all')
    expect(all.ranked.map((r) => [r.p.name, r.place])).toEqual([['А', 1], ['Б', 2], ['В', 3], ['Г', 4]])
    expect(all.unranked.map((r) => r.name)).toEqual(['Д'])
    const l1 = leaderboardRows(parts, 'L1')
    expect(l1.ranked.map((r) => [r.p.name, r.place])).toEqual([['А', 1], ['В', 2]])
    expect(leaderboardRows(parts, 'none').ranked.map((r) => r.p.name)).toEqual(['Г'])
  })

  it('моя дорожка закрепляется первой', () => {
    expect(pinMyLane(parts, 'В').map((r) => r.name)).toEqual(['В', 'А', 'Б', 'Г', 'Д'])
    expect(pinMyLane(parts, 'А').map((r) => r.name)[0]).toBe('А')
    expect(pinMyLane(parts, null)).toBe(parts)
  })
})

describe('форматы', () => {
  it('процент со знаком, запятой и неразрывным пробелом; null — тире', () => {
    expect(formatPct(18.25)).toBe(`+18,3${NBSP}%`)
    expect(formatPct(-4)).toBe(`−4,0${NBSP}%`)
    expect(formatPct(0)).toBe(`0,0${NBSP}%`)
    expect(formatPct(null)).toBe('—')
  })

  it('средняя — два знака после запятой', () => {
    expect(formatAvg(2.4)).toBe('2,40')
    expect(formatAvg(null)).toBe('—')
  })

  it('aria собирает код, имя, клетки, процент, место и динамику', () => {
    const text = laneAria(p({ code: 'П14', name: 'Невский', cells: 236, pct: 18, place: 2, dynamics: 'up' }), 'all')
    expect(text).toContain('П14 Невский')
    expect(text).toContain('236 клеток')
    expect(text).toContain('2-е место')
    expect(text).toContain('растёт')
    expect(laneAria(p({ needs_baseline: true }), 'all')).toContain('база не задана')
  })

  it('строка свежести', () => {
    const now = Date.UTC(2026, 8, 24, 10, 12)
    expect(freshnessLine(null, null, now)).toBeNull()
    expect(freshnessLine(new Date(now - 30_000).toISOString(), null, now)).toBe('Обновлено только что')
    expect(freshnessLine(new Date(now - 12 * 60_000).toISOString(), null, now)).toBe(`Обновлено 12${NBSP}минут назад`)
  })
})

describe('состояние экрана', () => {
  it('нет конкурса / запланировано / идёт / между заездами / завершено', () => {
    expect(boardState(board({ contest: null })).kind).toBe('no-contest')
    expect(boardState(board({ race: { ...race({ status: 'scheduled' }), days_total: 7, day_index: null, data_through: null } })).kind).toBe('scheduled')
    expect(boardState(board()).kind).toBe('active')
    const between = boardState(
      board({
        race: { ...race({ id: 'r2', seq: 2, status: 'scheduled' }), days_total: 7, day_index: null, data_through: null },
        finished_races: [{ ...race({ status: 'finished' }), winner_store_id: 'А' }],
      }),
    )
    expect(between.kind).toBe('between')
    expect(boardState(board({ contest: contest({ status: 'finished' }) })).kind).toBe('finished')
  })
})

describe('ТВ и URL', () => {
  it('страницы ТВ: 63 по 17 → 4 страницы, последняя из 12; пусто → одна пустая', () => {
    const rows = Array.from({ length: 63 }, (_, i) => i)
    const pages = tvPages(rows, 17)
    expect(pages.length).toBe(4)
    expect(pages[3]?.length).toBe(12)
    expect(tvPages([], 17)).toEqual([[]])
    expect(tvPages([1, 2], 0).length).toBe(2)
    expect(tvPageSize(1080, 48, 300)).toBe(16)
  })

  it('setRaceParams не трогает чужие ключи и убирает дефолты', () => {
    const params = new URLSearchParams('tab=race&league=L1')
    const next = setRaceParams(params, { league: 'all', store: 'S' })
    expect(next.get('tab')).toBe('race')
    expect(next.get('league')).toBeNull()
    expect(next.get('store')).toBe('S')
    expect(resolveRaceParams(next)).toEqual({ league: null, race: null, store: 'S' })
  })
})
