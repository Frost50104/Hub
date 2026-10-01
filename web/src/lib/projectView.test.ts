import { describe, expect, it } from 'vitest'

import { isProjectView, PROJECT_VIEWS, resolveProjectView } from './projectView'

const base = { requested: null, stageCount: undefined, stagesFailed: false, showDashboard: true }

describe('resolveProjectView', () => {
  it('явный вид побеждает при любом состоянии колонок', () => {
    expect(resolveProjectView({ ...base, requested: 'board', stageCount: 0 })).toBe('board')
    expect(resolveProjectView({ ...base, requested: 'list', stageCount: undefined })).toBe('list')
    expect(resolveProjectView({ ...base, requested: 'about', stageCount: undefined })).toBe('about')
  })

  it('неизвестный вид — как отсутствующий', () => {
    expect(resolveProjectView({ ...base, requested: 'foo', stageCount: 3 })).toBe('board')
    expect(resolveProjectView({ ...base, requested: 'foo', stageCount: 0 })).toBe('list')
  })

  it('без вида и без колонок в кэше — null: страница рисует скелет', () => {
    expect(resolveProjectView(base)).toBeNull()
  })

  it('без вида: колонки есть — доска, нет — список', () => {
    expect(resolveProjectView({ ...base, stageCount: 3 })).toBe('board')
    expect(resolveProjectView({ ...base, stageCount: 1 })).toBe('board')
    expect(resolveProjectView({ ...base, stageCount: 0 })).toBe('list')
  })

  it('запрос колонок упал — список, без ожидания', () => {
    expect(resolveProjectView({ ...base, stagesFailed: true })).toBe('list')
    expect(resolveProjectView({ ...base, stagesFailed: true, requested: 'calendar' })).toBe('calendar')
  })

  it('дашборд у шаблона — не запрошено, уходит в дефолт', () => {
    const tpl = { ...base, requested: 'dashboard', showDashboard: false }
    expect(resolveProjectView({ ...tpl, stageCount: 2 })).toBe('board')
    expect(resolveProjectView({ ...tpl, stageCount: 0 })).toBe('list')
    expect(resolveProjectView({ ...tpl, stageCount: undefined })).toBeNull()
    expect(resolveProjectView({ ...base, requested: 'dashboard', showDashboard: true })).toBe('dashboard')
  })
})

describe('isProjectView', () => {
  it('знает все вкладки и не знает чужих', () => {
    for (const v of PROJECT_VIEWS) expect(isProjectView(v.key)).toBe(true)
    expect(isProjectView('foo')).toBe(false)
    expect(isProjectView(null)).toBe(false)
    expect(isProjectView(undefined)).toBe(false)
  })
})
