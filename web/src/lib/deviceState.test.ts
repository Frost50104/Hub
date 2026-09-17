import { describe, expect, it } from 'vitest'

import { PER_USER_LOCAL_KEYS, PER_USER_SESSION_KEYS } from './deviceState'

/**
 * Часовой над списком чистки при выходе. Тест нужен именно списочный: обе
 * ошибки здесь молчаливые — забытый ключ оставляет следы человека на общем
 * устройстве, лишний ломает вход или уведомления, и ни то ни другое не видно
 * ни в типах, ни в сборке.
 */
describe('чистка устройства при выходе', () => {
  it('снимает всё, что принадлежит вошедшему человеку', () => {
    expect([...PER_USER_LOCAL_KEYS]).toEqual([
      'hub-theme',
      'hub-theme-owner',
      'hub-space',
      'hub-view-config',
      'hub-project-folders',
      'hub:push-last-sync',
      'hub:push-owner',
    ])
    expect([...PER_USER_SESSION_KEYS]).toEqual(['hub:push-prompt-dismissed'])
  })

  it('НЕ трогает разрешение на уведомления — иначе вернувшемуся включать заново', () => {
    expect(PER_USER_LOCAL_KEYS).not.toContain('hub:push-opted-in')
  })

  it('НЕ трогает служебные ключи логина и гард перезагрузок', () => {
    const all: readonly string[] = [...PER_USER_LOCAL_KEYS, ...PER_USER_SESSION_KEYS]
    expect(all).not.toContain('sso_pkce_verifier')
    expect(all).not.toContain('sso_return_path')
    expect(all).not.toContain('hub:preload-reload-at')
  })

  // С либы 0.12 запись попытки входа живёт под `sso_pkce:<state>` и в
  // `localStorage` тоже — чтобы callback в другой вкладке мог завершить обмен.
  // Ключ переменный, поэтому «не содержит» его не поймает: сторожим префикс.
  it('НЕ трогает запись попытки входа sso_pkce:<state> (либа 0.12)', () => {
    const all: readonly string[] = [...PER_USER_LOCAL_KEYS, ...PER_USER_SESSION_KEYS]
    expect(all.filter((k) => k.startsWith('sso_pkce'))).toEqual([])
  })
})
