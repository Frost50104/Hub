import { describe, expect, it } from 'vitest'

import { adminSegmentsFor, canManageCourses, coursesSectionTitle } from './learnNav'

/** Гейты «Управления» повторяют бэкенд: офис без publisher не видит ни
 *  «Проверку», ни «Аналитику» (оба 403 на сервере — QA-0821 #24). */
describe('adminSegmentsFor', () => {
  const me = (hub_role: string | null, org_role: string, content_role = 'none') => ({
    hub_role,
    profile: { org_role, content_role },
  })

  it('admin получает все сегменты', () => {
    expect(adminSegmentsFor(me('admin', 'employee'))).toEqual([
      'review',
      'analytics',
      'progress',
      'employees',
      'automations',
      'audit',
      'org',
    ])
  })

  it('офис без publisher — ничего', () => {
    expect(adminSegmentsFor(me('member', 'office'))).toEqual([])
  })

  it('офис с publisher — проверка, аналитика и прогресс', () => {
    expect(adminSegmentsFor(me('member', 'office', 'publisher'))).toEqual([
      'review',
      'analytics',
      'progress',
    ])
  })

  it('ТУ и франчайзи без publisher — аналитика и прогресс (скоуп точек)', () => {
    expect(adminSegmentsFor(me('member', 'tu'))).toEqual(['analytics', 'progress'])
    expect(adminSegmentsFor(me('member', 'franchisee_owner'))).toEqual([
      'analytics',
      'progress',
    ])
  })

  /** Порядок не косметика: `LearnAdminPage` берёт `allowed[0]` как вкладку по
   *  умолчанию, поэтому `progress` перед `analytics` молча увёл бы каждого ТУ
   *  с привычного экрана на новый. */
  it('прогресс идёт ПОСЛЕ аналитики — иначе сменится вкладка по умолчанию', () => {
    for (const who of [me('admin', 'employee'), me('member', 'tu'), me('member', 'office', 'publisher')]) {
      const segments = adminSegmentsFor(who)
      expect(segments.indexOf('progress')).toBeGreaterThan(segments.indexOf('analytics'))
    }
  })

  it('линейный сотрудник и отсутствие профиля — ничего', () => {
    expect(adminSegmentsFor(me('member', 'employee'))).toEqual([])
    expect(adminSegmentsFor({ hub_role: 'member', profile: null })).toEqual([])
    expect(adminSegmentsFor(undefined)).toEqual([])
  })
})

describe('canManageCourses', () => {
  it.each([
    ['admin' as const, 'none' as const],
    ['member' as const, 'author' as const],
    ['member' as const, 'publisher' as const],
    ['viewer' as const, 'admin' as const],
  ])('hub=%s content=%s — ведёт курсы', (hubRole, contentRole) => {
    expect(canManageCourses(contentRole, hubRole)).toBe(true)
  })

  it('обычный сотрудник курсы только проходит', () => {
    expect(canManageCourses('none', 'member')).toBe(false)
    expect(canManageCourses(null, null)).toBe(false)
    expect(canManageCourses(undefined, undefined)).toBe(false)
  })

  it('совпадает с заголовком раздела — правило одно', () => {
    for (const [content, hub] of [
      ['none', 'admin'],
      ['author', 'member'],
      ['none', 'member'],
    ] as const) {
      const manages = canManageCourses(content, hub)
      expect(coursesSectionTitle(content, hub)).toBe(manages ? 'Учебные курсы' : 'Моё обучение')
    }
  })

})
