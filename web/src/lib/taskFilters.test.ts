import { describe, expect, it } from 'vitest'

import {
  activeFilterCount,
  applyFiltersToSearchParams,
  filtersFromSearchParams,
  toCalendarFilters,
  toListFilters,
  type TaskViewFilters,
} from './taskFilters'

describe('filtersFromSearchParams', () => {
  it('читает все ключи из URL', () => {
    const sp = new URLSearchParams(
      'f_assignee=u1&f_status=done&f_priority=high&f_label=l1&f_due=week&sort=due_at&order=desc',
    )
    expect(filtersFromSearchParams(sp)).toEqual({
      assignee: 'u1',
      status: 'done',
      priority: 'high',
      label: 'l1',
      due: 'week',
      sort: 'due_at',
      order: 'desc',
    })
  })

  it('отбрасывает мусорные значения enum-полей', () => {
    const sp = new URLSearchParams('f_status=hacked&f_priority=&sort=nope')
    const f = filtersFromSearchParams(sp)
    expect(f.status).toBeUndefined()
    expect(f.priority).toBeUndefined()
    expect(f.sort).toBeUndefined()
  })
})

describe('applyFiltersToSearchParams', () => {
  it('пишет активные и стирает пустые, не трогая чужие ключи', () => {
    const sp = new URLSearchParams('task=t1&f_status=done')
    applyFiltersToSearchParams(sp, { assignee: 'u2' })
    expect(sp.get('task')).toBe('t1')
    expect(sp.get('f_assignee')).toBe('u2')
    expect(sp.get('f_status')).toBeNull()
  })
})

describe('activeFilterCount', () => {
  it('не считает сортировку фильтром', () => {
    expect(activeFilterCount({ sort: 'title', order: 'asc' })).toBe(0)
    expect(activeFilterCount({ assignee: 'u', label: 'l', due: 'today' })).toBe(3)
  })
})

describe('toListFilters', () => {
  const base: TaskViewFilters = {
    assignee: 'u1',
    status: 'todo',
    priority: 'low',
    label: 'l1',
    sort: 'due_at',
    order: 'desc',
  }

  it('переносит фильтры и сортировку', () => {
    expect(toListFilters(base)).toEqual({
      assignee: 'u1',
      status: 'todo',
      priority: 'low',
      label: 'l1',
      sort: 'due_at',
      order: 'desc',
    })
  })

  it('forBoard: сортировка отбрасывается (drag требует position)', () => {
    const out = toListFilters(base, { forBoard: true })
    expect(out.sort).toBeUndefined()
    expect(out.order).toBeUndefined()
    expect(out.assignee).toBe('u1')
  })

  it('due-пресет разворачивается в стабильный диапазон', () => {
    const a = toListFilters({ due: 'overdue' })
    const b = toListFilters({ due: 'overdue' })
    expect(a.due_to).toBeDefined()
    expect(a.due_from).toBeUndefined()
    // Стабильность в течение дня — иначе queryKey меняется на каждом рендере.
    expect(a.due_to).toBe(b.due_to)

    const today = toListFilters({ due: 'today' })
    expect(today.due_from).toBeDefined()
    expect(today.due_to).toBeDefined()
  })
})

describe('toCalendarFilters', () => {
  it('переносит только то, что умеет calendar-эндпоинт', () => {
    expect(
      toCalendarFilters({
        assignee: 'u1',
        status: 'done',
        priority: 'high',
        label: 'l1',
        due: 'week',
        sort: 'title',
      }),
    ).toEqual({ assignee: 'u1', status: 'done', priority: 'high' })
  })
})
