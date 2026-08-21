import { describe, expect, it } from 'vitest'

import { adminSegmentsFor } from './learnNav'

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
      'employees',
      'automations',
      'audit',
      'org',
    ])
  })

  it('офис без publisher — ничего', () => {
    expect(adminSegmentsFor(me('member', 'office'))).toEqual([])
  })

  it('офис с publisher — проверка и аналитика', () => {
    expect(adminSegmentsFor(me('member', 'office', 'publisher'))).toEqual(['review', 'analytics'])
  })

  it('ТУ и франчайзи без publisher — только аналитика (скоуп магазинов)', () => {
    expect(adminSegmentsFor(me('member', 'tu'))).toEqual(['analytics'])
    expect(adminSegmentsFor(me('member', 'franchisee_owner'))).toEqual(['analytics'])
  })

  it('линейный сотрудник и отсутствие профиля — ничего', () => {
    expect(adminSegmentsFor(me('member', 'employee'))).toEqual([])
    expect(adminSegmentsFor({ hub_role: 'member', profile: null })).toEqual([])
    expect(adminSegmentsFor(undefined)).toEqual([])
  })
})
