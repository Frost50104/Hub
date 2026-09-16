import { describe, expect, it } from 'vitest'

import {
  AUTH_STATE_LABEL,
  authStateTone,
  matchesAuthFilter,
  showAuthStateBadge,
  staffSyncToast,
} from './authState'

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

  it('«приглашён(а)» — внимание (амбер), с собственной подписью', () => {
    expect(authStateTone('invited')).toBe('amber')
    expect(AUTH_STATE_LABEL.invited).toBe('Приглашён(а) в auth')
    expect(showAuthStateBadge('invited')).toBe(true)
  })

  it('фильтр «Без учётки» держит приглашённых и осторожное not_linked', () => {
    expect(matchesAuthFilter('no_account', 'no_account')).toBe(true)
    expect(matchesAuthFilter('no_account', 'invited')).toBe(true)
    expect(matchesAuthFilter('no_account', 'not_linked')).toBe(true)
    expect(matchesAuthFilter('no_account', 'active')).toBe(false)
    expect(matchesAuthFilter('not_logged_in', 'not_logged_in')).toBe(true)
    expect(matchesAuthFilter('not_logged_in', 'invited')).toBe(false)
    expect(matchesAuthFilter('all', null)).toBe(true)
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
