import { describe, expect, it } from 'vitest'

import { resolveEnvLabel } from './appEnv'

describe('resolveEnvLabel', () => {
  it('на проде молчит', () => {
    // Бэкенд зовёт прод `prod`, сборка — `production`. Проверка против
    // одного из написаний зажгла бы маркер на боевом домене.
    expect(resolveEnvLabel('production', 'prod')).toBeNull()
    expect(resolveEnvLabel('production', 'production')).toBeNull()
  })

  it('молчит, если /api/env не ответил, а сборка продовая', () => {
    expect(resolveEnvLabel('production', null)).toBeNull()
    expect(resolveEnvLabel('production', undefined)).toBeNull()
  })

  it('помечает staging-сборку', () => {
    expect(resolveEnvLabel('staging', 'staging')).toBe('STAGING')
  })

  it('помечает прод-сборку, положенную на staging-бэкенд', () => {
    // Ручной rsync мимо deploy.sh: бандл считает себя продом, а API отвечает
    // staging'овое. Без второго плеча маркера бы не было.
    expect(resolveEnvLabel('production', 'staging')).toBe('STAGING')
  })

  it('помечает локальную разработку', () => {
    expect(resolveEnvLabel('development', null)).toBe('DEV')
  })

  it('незнакомое окружение показывает как есть', () => {
    expect(resolveEnvLabel('qa', null)).toBe('QA')
  })
})
