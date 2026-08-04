import { describe, expect, it, vi } from 'vitest'

import { isNeutralPath, resolveSpace, spaceFromPath } from './workspace'

describe('spaceFromPath', () => {
  it('классифицирует learn-роуты', () => {
    expect(spaceFromPath('/learn')).toBe('learn')
    expect(spaceFromPath('/learn/courses/abc')).toBe('learn')
    expect(spaceFromPath('/learn/admin/org')).toBe('learn')
  })

  it('не ловится на префикс-ловушку /learnx', () => {
    expect(spaceFromPath('/learnx')).toBe('tasks')
  })

  it('всё остальное — tasks', () => {
    expect(spaceFromPath('/')).toBe('tasks')
    expect(spaceFromPath('/my')).toBe('tasks')
    expect(spaceFromPath('/projects/p1')).toBe('tasks')
  })
})

describe('isNeutralPath', () => {
  it('точные нейтральные роуты', () => {
    expect(isNeutralPath('/inbox')).toBe(true)
    expect(isNeutralPath('/search')).toBe(true)
    expect(isNeutralPath('/profile')).toBe(true)
    expect(isNeutralPath('/settings')).toBe(true)
  })

  it('вложенные нейтральные роуты', () => {
    expect(isNeutralPath('/settings/notifications')).toBe(true)
    expect(isNeutralPath('/settings/appearance')).toBe(true)
  })

  it('не-нейтральные и префикс-ловушки', () => {
    expect(isNeutralPath('/')).toBe(false)
    expect(isNeutralPath('/inboxx')).toBe(false)
    expect(isNeutralPath('/learn')).toBe(false)
    expect(isNeutralPath('/my')).toBe(false)
  })
})

describe('resolveSpace', () => {
  it('learn-роуты → learn при любом lastSpace', () => {
    expect(resolveSpace('/learn', 'tasks')).toBe('learn')
    expect(resolveSpace('/learn/library', 'tasks')).toBe('learn')
    expect(resolveSpace('/learn', 'learn')).toBe('learn')
  })

  it('нейтральные роуты наследуют lastSpace', () => {
    for (const p of ['/inbox', '/search', '/profile', '/settings/notifications']) {
      expect(resolveSpace(p, 'learn')).toBe('learn')
      expect(resolveSpace(p, 'tasks')).toBe('tasks')
    }
  })

  it('явные task-роуты → tasks даже при lastSpace=learn', () => {
    expect(resolveSpace('/', 'learn')).toBe('tasks')
    expect(resolveSpace('/my', 'learn')).toBe('tasks')
    expect(resolveSpace('/projects/p1', 'learn')).toBe('tasks')
  })
})

describe('consumeBootSpaceRedirect', () => {
  it('true ровно один раз за загрузку модуля', async () => {
    vi.resetModules()
    const mod = await import('./workspace')
    expect(mod.consumeBootSpaceRedirect()).toBe(true)
    expect(mod.consumeBootSpaceRedirect()).toBe(false)
    expect(mod.consumeBootSpaceRedirect()).toBe(false)
  })

  it('свежий модуль — свежий флаг', async () => {
    vi.resetModules()
    const mod = await import('./workspace')
    expect(mod.consumeBootSpaceRedirect()).toBe(true)
  })
})
