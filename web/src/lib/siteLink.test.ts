import { describe, expect, it } from 'vitest'

import type { OrgStore, SiteMirror } from './learn'
import { duplicateGroups, mergeSummary, pendingHint, siteDisplay, sitePickerOptions } from './siteLink'

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

describe('привязка к объекту реестра (19.09)', () => {
  const s1 = { ...site, site_id: 'x1', name: 'Арсенальная', code: 'А1' }
  const s2 = { ...site, site_id: 'x2', name: 'Витебский 101', code: 'В101' }
  const s3 = { ...site, site_id: 'x3', name: 'Закрытая', archived_at: '2026-09-19T00:00:00Z' }

  it('занятые живой карточкой и архивные объекты не предлагаются, текущий — всегда', () => {
    const stores = [
      store({ id: 'a', site_id: 'x1' }),
      store({ id: 'b', site_id: 'x2', archived_at: '2026-09-01T00:00:00Z' }),
    ]
    expect(sitePickerOptions([s1, s2, s3], stores, { storeId: 'c', siteId: null }).map((o) => o.value)).toEqual(['x2'])
    expect(sitePickerOptions([s1, s2, s3], stores, { storeId: 'a', siteId: 'x1' }).map((o) => o.value)).toEqual(['x1', 'x2'])
    expect(sitePickerOptions([s1], stores, { storeId: 'a', siteId: 'x1' })[0]).toMatchObject({ label: 'А1 · Арсенальная', meta: 'СПб, Приморская 14' })
  })

  it('подсказка называет кандидата', () => {
    const base = { site_id: 'x', code: null, name: 'Смоленка 35', address: null, iiko_ref: null, candidate_store_id: null, candidate_store_name: null }
    expect(pendingHint({ ...base, reason: 'no_iiko_ref' })).toContain('нет подразделения iiko')
    expect(pendingHint({ ...base, reason: 'code_collision', candidate_store_name: 'Смоленка' })).toContain('«Смоленка»')
    expect(pendingHint({ ...base, reason: 'name_collision' })).toContain('карточкой без реестра')
  })
})

describe('слияние дублей (19.09)', () => {
  it('архивная карточка с тем же site_id пару не образует', () => {
    const live = store({ id: 'a', site_id: 'x1' })
    const gone = store({ id: 'b', site_id: 'x1', archived_at: '2026-09-19T00:00:00Z' })
    expect(duplicateGroups([live, gone])).toEqual([])
    expect(duplicateGroups([live, store({ id: 'c', site_id: 'x1' })])).toHaveLength(1)
  })

  it('сводка перечисляет только ненулевое и сворачивает удаляемые дубли', () => {
    expect(mergeSummary({ profiles: 2, shifts: 0, race_participants_dropped: 1, group_members_dropped: 1 })).toBe(
      '2 сотрудников, 2 дублирующих строк удалится',
    )
    expect(mergeSummary({})).toBe('ничего — у проигравшей карточки нет данных')
  })
})
