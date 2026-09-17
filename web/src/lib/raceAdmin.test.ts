import { describe, expect, it } from 'vitest'

import type { OrgGroup, OrgStore } from './learn'
import {
  canCreateContest,
  contestEndsOn,
  defaultDraft,
  leagueOverlaps,
  parseBaselineInput,
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
