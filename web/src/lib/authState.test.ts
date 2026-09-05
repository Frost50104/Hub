import { describe, expect, it } from 'vitest'

import { authStateTone, showAuthStateBadge, staffSyncToast } from './authState'

describe('authState', () => {
  it('норма не бейджится, внимание — амбер, закрытый доступ — красный', () => {
    expect(showAuthStateBadge('active')).toBe(false)
    expect(showAuthStateBadge(null)).toBe(false)
    expect(showAuthStateBadge('not_logged_in')).toBe(true)
    expect(authStateTone('no_account')).toBe('amber')
    expect(authStateTone('not_logged_in')).toBe('amber')
    expect(authStateTone('blocked')).toBe('red')
    expect(authStateTone('deleted')).toBe('red')
    expect(authStateTone('active')).toBeNull()
  })
})

describe('staffSyncToast', () => {
  const base = {
    available: true,
    dry_run: false,
    profiles_created: 3,
    profiles_linked: 2,
    email_conflicts: 0,
  }

  it('живой прогон — success, dry-run не врёт «синхронизировано»', () => {
    expect(staffSyncToast(base)).toEqual({
      kind: 'success',
      text: 'Синхронизировано: карточек создано 3, привязано 2',
    })
    const dry = staffSyncToast({ ...base, dry_run: true })
    expect(dry.kind).toBe('message')
    expect(dry.text).toContain('без записи')
    expect(dry.text).toContain('будет создано карточек 3')
    expect(dry.text).not.toContain('Синхронизировано')
  })

  it('недоступность и конфликты', () => {
    expect(staffSyncToast({ ...base, available: false }).kind).toBe('message')
    expect(staffSyncToast({ ...base, email_conflicts: 1 }).text).toContain(
      'конфликтов email: 1',
    )
  })
})
