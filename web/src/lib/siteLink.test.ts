import { describe, expect, it } from 'vitest'

import type { OrgStore, SiteMirror } from './learn'
import { duplicateGroups, siteDisplay } from './siteLink'

const store = (over: Partial<OrgStore> = {}): OrgStore => ({
  id: 's1',
  name: 'Приморская 14',
  code: 'П14',
  address: null,
  franchisee_id: null,
  archived_at: null,
  site_id: null,
  ...over,
})

const site: SiteMirror = {
  site_id: 'x1',
  code: 'П14',
  name: 'Приморская 14',
  address: 'СПб, Приморская 14',
  legal_name: 'ИП Тестова',
  inn: '780000000000',
  email: null,
  phone: null,
  archived_at: null,
  synced_at: '2026-09-05T12:00:00Z',
}

describe('siteDisplay — три состояния, не два', () => {
  it('без связи — локальные поля', () => {
    expect(siteDisplay(store(), site, true)).toEqual({ kind: 'none' })
  })
  it('связь + строка + свежий снимок — данные реестра', () => {
    expect(siteDisplay(store({ site_id: 'x1' }), site, true)).toEqual({
      kind: 'live',
      site,
    })
  })
  it('связь есть, но строки нет ИЛИ снимок протух — stale, не пустота', () => {
    // Ровно против тихо протухшего ключа: адрес не должен молча исчезнуть.
    expect(siteDisplay(store({ site_id: 'x1' }), undefined, true).kind).toBe('stale')
    expect(siteDisplay(store({ site_id: 'x1' }), site, false).kind).toBe('stale')
  })
})

describe('duplicateGroups', () => {
  it('группирует по site_id только count>1, без site_id не участвует', () => {
    const a = store({ id: 'a', name: 'Кораблестроителей 32/3 лит А.', site_id: 'dup' })
    const b = store({ id: 'b', name: 'Кораблестроителей 32А', site_id: 'dup' })
    const single = store({ id: 'c', site_id: 'solo' })
    const unlinked = store({ id: 'd' })
    const groups = duplicateGroups([single, b, unlinked, a])
    expect(groups).toHaveLength(1)
    expect(groups[0]?.site_id).toBe('dup')
    expect(groups[0]?.stores.map((s) => s.id).sort()).toEqual(['a', 'b'])
  })
})
