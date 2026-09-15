import { describe, expect, it } from 'vitest'

import { locationWithoutTask, projectLocation, taskLocation } from './taskLinks'

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

describe('projectLocation', () => {
  it('своё личное — вкладка «Личные» на «Моих задачах», без task', () => {
    expect(projectLocation({ projectId: 'p', personalProjectId: 'p' })).toBe('/my?tab=personal')
  })

  it('рабочий проект — его страница без параметров', () => {
    expect(projectLocation({ projectId: 'w', personalProjectId: 'p' })).toBe('/projects/w')
  })

  it('на той же странице фильтры остаются, а карточка закрывается', () => {
    // Клик по имени проекта на его же доске: `?view=board` нужен, `?task=` — нет.
    expect(
      projectLocation({
        projectId: 'w',
        personalProjectId: 'p',
        pathname: '/projects/w',
        search: '?view=board&task=t1',
      }),
    ).toBe('/projects/w?view=board')
  })

  it('с чужой вкладки «Моих задач» своё личное ведёт на вкладку «Личные»', () => {
    expect(
      projectLocation({
        projectId: 'p',
        personalProjectId: 'p',
        pathname: '/my',
        search: '?tab=all&task=t1',
      }),
    ).toBe('/my?tab=personal')
  })

  it('чужие фильтры не тащим', () => {
    expect(
      projectLocation({
        projectId: 'w',
        personalProjectId: 'p',
        pathname: '/projects/other',
        search: '?f_label=x',
      }),
    ).toBe('/projects/w')
  })

  it('без личного проекта — страница проекта', () => {
    expect(projectLocation({ projectId: 'p', personalProjectId: null })).toBe('/projects/p')
  })
})

describe('locationWithoutTask', () => {
  it('снимает только task', () => {
    expect(locationWithoutTask('/projects/w', '?view=board&task=t1')).toBe(
      '/projects/w?view=board',
    )
    expect(locationWithoutTask('/my', '?task=t1')).toBe('/my')
    expect(locationWithoutTask('/my', '')).toBe('/my')
  })

  it('совпадает с projectLocation, когда карточка открыта на странице своего проекта', () => {
    const here = { pathname: '/projects/w', search: '?task=t1&view=board' }
    expect(projectLocation({ projectId: 'w', personalProjectId: 'p', ...here })).toBe(
      locationWithoutTask(here.pathname, here.search),
    )
  })
})
