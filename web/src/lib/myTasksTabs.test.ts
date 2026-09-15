import { describe, expect, it } from 'vitest'

import {
  clearNewPersonalParams,
  isDueWindowTab,
  isGroupedTab,
  myTasksEmptyText,
  personalProjectRedirect,
  resolveMyTasksTab,
  setMyTasksTab,
} from './myTasksTabs'

const WITH_PERSONAL = { hasPersonal: true }

describe('resolveMyTasksTab', () => {
  it('без параметра открывает «Предстоит»', () => {
    expect(resolveMyTasksTab(new URLSearchParams(), WITH_PERSONAL)).toBe('upcoming')
  })

  it('неизвестное значение не роняет экран', () => {
    const params = new URLSearchParams('tab=doska')
    expect(resolveMyTasksTab(params, WITH_PERSONAL)).toBe('upcoming')
  })

  it('«Личные» без личного проекта подменяются дефолтом', () => {
    const params = new URLSearchParams('tab=personal')
    expect(resolveMyTasksTab(params, { hasPersonal: false })).toBe('upcoming')
  })

  it('?new=personal открывает «Личные» даже без ?tab=', () => {
    // Ссылка из FAB. Иначе «Личная задача» приводила бы на вкладку, где инпута
    // создания нет вовсе — и старые бандлы шлют именно этот адрес.
    const params = new URLSearchParams('new=personal')
    expect(resolveMyTasksTab(params, WITH_PERSONAL)).toBe('personal')
  })

  it('?new=personal без личного проекта не ломает экран', () => {
    const params = new URLSearchParams('new=personal')
    expect(resolveMyTasksTab(params, { hasPersonal: false })).toBe('upcoming')
  })
})

describe('setMyTasksTab', () => {
  it('дефолт из адреса убирает, остальное пишет', () => {
    expect(setMyTasksTab(new URLSearchParams('tab=all'), 'upcoming').toString()).toBe('')
    expect(setMyTasksTab(new URLSearchParams(), 'personal').get('tab')).toBe('personal')
  })

  it('закрывает карточку и гасит одноразовый ?new=', () => {
    const params = new URLSearchParams('tab=personal&task=abc&new=personal')
    const next = setMyTasksTab(params, 'all')
    expect(next.get('task')).toBeNull()
    expect(next.get('new')).toBeNull()
  })
})

describe('clearNewPersonalParams', () => {
  it('снимает ?new=, оставляя вкладку «Личные»', () => {
    // Снять `new`, не поставив `tab`, значит выкинуть человека на «Предстоит»
    // сразу после того, как он попросил создать личную задачу.
    const next = clearNewPersonalParams(new URLSearchParams('new=personal'))
    expect(next.get('new')).toBeNull()
    expect(next.get('tab')).toBe('personal')
  })
})

describe('personalProjectRedirect', () => {
  it('переносит ?task= — по таким адресам ведут пуши и «Входящие»', () => {
    const to = personalProjectRedirect(new URLSearchParams('task=t-1&view=board'))
    expect(to).toContain('task=t-1')
    expect(to).toContain('tab=personal')
  })

  it('выбрасывает вид и фильтры проекта: их у личного больше нет', () => {
    const to = personalProjectRedirect(
      new URLSearchParams('view=board&f_priority=high&f_label=x'),
    )
    expect(to).toBe('/my?tab=personal')
  })
})

describe('вкладки', () => {
  it('окна дедлайнов отделены от «пространств»', () => {
    expect(isDueWindowTab('upcoming')).toBe(true)
    expect(isDueWindowTab('personal')).toBe(false)
    expect(isDueWindowTab('assigned')).toBe(false)
  })

  it('группируются по срокам только «Все» и «Предстоит»', () => {
    expect(isGroupedTab('all')).toBe(true)
    expect(isGroupedTab('upcoming')).toBe(true)
    expect(isGroupedTab('today')).toBe(false)
    expect(isGroupedTab('personal')).toBe(false)
  })

  it('у каждой вкладки свой текст пустого состояния', () => {
    const texts = (['upcoming', 'today', 'overdue', 'all', 'personal', 'assigned'] as const)
      .map(myTasksEmptyText)
    expect(new Set(texts).size).toBeGreaterThan(3)
    expect(myTasksEmptyText('assigned')).toContain('не ставили')
  })
})
