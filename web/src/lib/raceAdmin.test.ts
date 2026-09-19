import { describe, expect, it } from 'vitest'

import type { OrgGroup, OrgStore } from './learn'
import {
  canCreateContest,
  contestEndsOn,
  defaultDraft,
  earlyStartLabel,
  earlyStartText,
  leagueOverlaps,
  parseBaselineInput,
  raceLengthNote,
  racesPreview,
  setRaceAdminParams,
  validateContestDraft,
} from './raceAdmin'

const store = (id: string, name: string, archived = false): OrgStore => ({
  id,
  name,
  code: null,
  address: null,
  franchisee_id: null,
  archived_at: archived ? '2026-01-01T00:00:00Z' : null,
  site_id: null,
})
const group = (id: string, name: string, members: string[]): OrgGroup => ({ id, name, description: null, member_ids: members })

describe('черновик конкурса', () => {
  it('окончание — старт + 28 дней − 1; заезды встык: 7 → 4, 14 → 2', () => {
    expect(contestEndsOn('2026-09-21', 4)).toBe('2026-10-18')
    const r7 = racesPreview('2026-09-21', 4, 7)
    expect(r7.map((r) => [r.seq, r.starts_on, r.ends_on])).toEqual([
      [1, '2026-09-21', '2026-09-27'],
      [2, '2026-09-28', '2026-10-04'],
      [3, '2026-10-05', '2026-10-11'],
      [4, '2026-10-12', '2026-10-18'],
    ])
    expect(racesPreview('2026-09-21', 4, 14)).toHaveLength(2)
    expect(racesPreview('2026-09-21', 3, 14)).toEqual([])
  })

  it('валидация зеркалит сервер: имя, дата, 7|14, кратность, ретро 7..92', () => {
    const today = '2026-09-17'
    expect(validateContestDraft(defaultDraft(today), today).ok).toBe(true)
    expect(validateContestDraft({ ...defaultDraft(today), title: ' ' }, today).errors.title).toBeTruthy()
    expect(validateContestDraft({ ...defaultDraft(today), starts_on: '2026-09-01' }, today).errors.starts_on).toBe('Дата старта уже прошла')
    expect(validateContestDraft({ ...defaultDraft(today), starts_on: '2026-09-01' }, today, true).ok).toBe(true)
    expect(validateContestDraft({ ...defaultDraft(today), weeks_total: 3, race_length_days: 14 }, today).errors.weeks_total).toBeTruthy()
    expect(validateContestDraft({ ...defaultDraft(today), baseline_days: 3 }, today).errors.baseline_days).toBeTruthy()
    expect(validateContestDraft({ ...defaultDraft(today), baseline_days: 120 }, today).errors.baseline_days).toBeTruthy()
  })

  it('пересечение лиг называет точку и обе группы, архивные не считаются', () => {
    const stores = [store('A', 'Арсенальная'), store('B', 'Ветеранов'), store('Z', 'Закрытая', true)]
    const groups = [group('g1', 'Центр', ['A', 'Z']), group('g2', 'Область', ['A', 'B', 'Z']), group('g3', 'Другая', ['B'])]
    expect(leagueOverlaps(['g1', 'g2'], groups, stores)).toEqual([{ storeId: 'A', name: 'Арсенальная', groupNames: ['Центр', 'Область'] }])
    expect(leagueOverlaps(['g1', 'g3'], groups, stores)).toEqual([])
  })

  it('новый конкурс — только когда нет черновика, запланированного или активного', () => {
    expect(canCreateContest([{ status: 'finished' }, { status: 'cancelled' }])).toBe(true)
    expect(canCreateContest([{ status: 'active' }])).toBe(false)
    expect(canCreateContest([{ status: 'draft' }])).toBe(false)
  })

  it('ввод базы: запятая допустима, ноль и мусор — ошибка', () => {
    expect(parseBaselineInput('2,35')).toEqual({ value: 2.35 })
    expect(parseBaselineInput('2.4')).toEqual({ value: 2.4 })
    expect(parseBaselineInput('0')).toHaveProperty('error')
    expect(parseBaselineInput('abc')).toHaveProperty('error')
    expect(parseBaselineInput('2.345')).toHaveProperty('error')
    expect(parseBaselineInput('')).toHaveProperty('error')
  })

  it('параметры вкладки не трогают tab', () => {
    const next = setRaceAdminParams(new URLSearchParams('tab=race&contest=c1'), { brace: 'r2', contest: null })
    expect(next.get('tab')).toBe('race')
    expect(next.get('contest')).toBeNull()
    expect(next.get('brace')).toBe('r2')
  })
})

describe('ранний старт заезда', () => {
  const today = '2026-09-23'
  const race = { seq: 2, starts_on: '2026-09-28', ends_on: '2026-10-04' }
  const contest = { race_length_days: 7, baseline_mode: 'contest' as const, baseline_days: 28 }

  it('подпись кнопки: сегодня / завтра / дата', () => {
    expect(earlyStartLabel('2026-09-23', today)).toBe('Начать сегодня')
    expect(earlyStartLabel('2026-09-24', today)).toBe('Начать завтра')
    expect(earlyStartLabel('2026-09-26', today)).toBe('Начать 26.09.2026')
  })

  it('текст подтверждения: новая дата, окончание прежнее, длина против плана', () => {
    const text = earlyStartText(race, '2026-09-24', contest, today)
    expect(text).toContain('Заезд № 2 стартует завтра вместо 28.09.2026.')
    expect(text).toContain('Окончание не меняется — 04.10.2026')
    expect(text).toContain('11\u00a0дней вместо 7')
    expect(text).not.toContain('iiko')
  })

  it('режим «база на заезд»: про iiko — только при старте сегодня', () => {
    const raceMode = { ...contest, baseline_mode: 'race' as const }
    expect(earlyStartText(race, today, raceMode, today)).toContain('База пересчитается из iiko за 28\u00a0дней')
    expect(earlyStartText(race, '2026-09-24', raceMode, today)).not.toContain('iiko')
  })

  it('подпись длины: только когда заезд длиннее плана', () => {
    expect(raceLengthNote(race, 7)).toBeNull()
    expect(raceLengthNote({ starts_on: '2026-09-24', ends_on: '2026-10-04' }, 7)).toBe('· 11\u00a0дней вместо 7')
    expect(raceLengthNote({ starts_on: '2026-10-03', ends_on: '2026-10-04' }, 7)).toBe('· 2\u00a0дня вместо 7')
  })
})
