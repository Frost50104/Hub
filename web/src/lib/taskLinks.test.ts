import { describe, expect, it } from 'vitest'

import { taskLocation } from './taskLinks'

describe('taskLocation', () => {
  it('личная задача открывается на «Моих задачах», на вкладке «Личные»', () => {
    const got = taskLocation({ taskId: 't1', projectId: 'p', personalProjectId: 'p' })
    expect(got.pathname).toBe('/my')
    expect(got.search).toContain('tab=personal')
    expect(got.search).toContain('task=t1')
  })

  it('рабочая — на странице своего проекта', () => {
    const got = taskLocation({ taskId: 't1', projectId: 'w', personalProjectId: 'p' })
    expect(got.pathname).toBe('/projects/w')
    expect(got.search).toBe('?task=t1')
  })

  it('на своей же странице фильтры сохраняются', () => {
    const got = taskLocation({
      taskId: 't1',
      projectId: 'w',
      personalProjectId: 'p',
      pathname: '/projects/w',
      search: '?view=board&f_priority=high',
    })
    expect(got.search).toContain('view=board')
    expect(got.search).toContain('f_priority=high')
  })

  it('чужие фильтры не тащим', () => {
    const got = taskLocation({
      taskId: 't1',
      projectId: 'w',
      personalProjectId: 'p',
      pathname: '/projects/other',
      search: '?f_label=x',
    })
    expect(got.search).toBe('?task=t1')
  })

  it('без личного проекта задача открывается как рабочая', () => {
    const got = taskLocation({ taskId: 't1', projectId: 'p', personalProjectId: null })
    expect(got.pathname).toBe('/projects/p')
  })
})
