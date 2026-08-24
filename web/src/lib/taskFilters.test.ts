import { describe, expect, it } from 'vitest'

import {
  activeFilterCount,
  applyFiltersToSearchParams,
  countOpenDone,
  describeFilters,
  filtersFromSearchParams,
  narrowableFilter,
  sinkDone,
  toCalendarFilters,
  toListFilters,
  type TaskViewFilters,
} from './taskFilters'

describe('filtersFromSearchParams', () => {
  it('читает все ключи из URL', () => {
    const sp = new URLSearchParams(
      'f_assignee=u1&f_done=done&f_priority=high&f_label=l1&f_due=week&sort=due_at&order=desc',
    )
    expect(filtersFromSearchParams(sp)).toEqual({
      assignee: 'u1',
      done: 'done',
      priority: 'high',
      label: 'l1',
      due: 'week',
      sort: 'due_at',
      order: 'desc',
    })
  })

  it('отбрасывает мусорные значения enum-полей', () => {
    const sp = new URLSearchParams('f_done=hacked&f_priority=&sort=nope')
    const f = filtersFromSearchParams(sp)
    expect(f.done).toBeUndefined()
    expect(f.priority).toBeUndefined()
    expect(f.sort).toBeUndefined()
  })

  it('старая ссылка со статусом не теряет смысл', () => {
    // Ссылками уже поделились: «в работе» и «на проверке» — это «не выполнено».
    expect(filtersFromSearchParams(new URLSearchParams('f_status=in_progress')).done).toBe(
      'open',
    )
    expect(filtersFromSearchParams(new URLSearchParams('f_status=open')).done).toBe('open')
    expect(filtersFromSearchParams(new URLSearchParams('f_status=done')).done).toBe('done')
    expect(filtersFromSearchParams(new URLSearchParams('f_status=wat')).done).toBeUndefined()
  })
})

describe('applyFiltersToSearchParams', () => {
  it('пишет активные и стирает пустые, не трогая чужие ключи', () => {
    const sp = new URLSearchParams('task=t1&f_done=done')
    applyFiltersToSearchParams(sp, { assignee: 'u2' })
    expect(sp.get('task')).toBe('t1')
    expect(sp.get('f_assignee')).toBe('u2')
    expect(sp.get('f_done')).toBeNull()
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
    done: 'open',
    priority: 'low',
    label: 'l1',
    sort: 'due_at',
    order: 'desc',
  }

  it('переносит фильтры и сортировку', () => {
    expect(toListFilters(base)).toEqual({
      assignee: 'u1',
      done: false,
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
    // «Просрочено» само по себе означает «ещё не выполнено».
    expect(a.done).toBe(false)
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
        done: 'done',
        priority: 'high',
        label: 'l1',
        due: 'week',
        sort: 'title',
      }),
    ).toEqual({ assignee: 'u1', done: true, priority: 'high' })
  })
})

describe('narrowableFilter', () => {
  it('предлагает снять единственный активный фильтр', () => {
    expect(narrowableFilter({ priority: 'urgent' })).toEqual({
      key: 'priority',
      label: 'приоритет',
    })
  })

  it('молчит, когда активных фильтров несколько', () => {
    // Сняв один из двух, человек снова увидит пустой список — кнопка
    // выглядела бы сломанной, поэтому предлагаем общее «Сбросить фильтры».
    expect(narrowableFilter({ priority: 'urgent', assignee: 'me' })).toBeNull()
  })

  it('молчит, когда фильтров нет вовсе', () => {
    expect(narrowableFilter({})).toBeNull()
  })

  it('не считает сортировку фильтром', () => {
    expect(narrowableFilter({ sort: 'due_at', order: 'asc' })).toBeNull()
    expect(narrowableFilter({ sort: 'due_at', label: 'l1' })).toEqual({
      key: 'label',
      label: 'метку',
    })
  })
})

describe('describeFilters', () => {
  const labels = {
    done: { open: 'Не выполнено', done: 'Выполнено' },
    priority: { low: 'низкий', medium: 'средний', high: 'высокий', urgent: 'срочно' },
  } as const
  it('перечисляет применённые фильтры с именами', () => {
    expect(
      describeFilters(
        { assignee: 'u1', priority: 'urgent', due: 'week' },
        { assignee: 'Дмитрий Фёдоров' },
        labels,
      ),
    ).toBe('Исполнитель: Дмитрий Фёдоров · Приоритет: срочно · Срок: неделя')
  })
  it('без имени пишет «выбран», а не id', () => {
    expect(describeFilters({ assignee: 'u1', label: 'l1' }, {}, labels)).toBe(
      'Исполнитель: выбран · Метка: выбрана',
    )
  })
})

describe('фильтр состояния, sinkDone, countOpenDone', () => {
  it('«Не выполнено» проходит через URL и в параметры списка', () => {
    const f = filtersFromSearchParams(new URLSearchParams('f_done=open'))
    expect(f.done).toBe('open')
    expect(toListFilters(f).done).toBe(false)
    expect(
      filtersFromSearchParams(new URLSearchParams('f_done=whatever')).done,
    ).toBeUndefined()
  })
  it('пресет «просрочено» без состояния фильтрует только невыполненные', () => {
    expect(toListFilters({ due: 'overdue' }).done).toBe(false)
    expect(toListFilters({ due: 'overdue', done: 'done' }).done).toBe(true)
    expect(toListFilters({ due: 'today' }).done).toBeUndefined()
  })
  it('sinkDone стабильно переносит выполненные в конец', () => {
    const tasks = [
      { id: 'a', done: true },
      { id: 'b', done: false },
      { id: 'c', done: true },
      { id: 'd', done: false },
    ] as const
    expect(sinkDone(tasks).map((t) => t.id)).toEqual(['b', 'd', 'a', 'c'])
    expect(sinkDone([]).length).toBe(0)
    expect(countOpenDone(tasks)).toEqual({ open: 2, done: 2 })
  })
})

