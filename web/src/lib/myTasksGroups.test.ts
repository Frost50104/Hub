import { describe, expect, it } from 'vitest'

import { groupKeyFor, groupTasksByDue, GROUP_ORDER } from './myTasksGroups'
import { dueDayToIso, todayKey, addDaysKey } from './taskDates'
import { type Task } from './tasks'

const task = (due: string | null, done = false) =>
  ({ due_at: due, done }) as unknown as Task

const today = todayKey()
const iso = (dayOffset: number) => dueDayToIso(addDaysKey(today, dayOffset))

describe('groupKeyFor', () => {
  it('без срока — «Без срока», а не «просрочено»', () => {
    // Ровно случай из ОС 15.09: задача без даты не должна теряться.
    expect(groupKeyFor(task(null), today)).toBe('nodate')
  })

  it('вчера и не выполнена — просрочено', () => {
    expect(groupKeyFor(task(iso(-1)), today)).toBe('overdue')
  })

  it('сегодня — «Сегодня»', () => {
    expect(groupKeyFor(task(iso(0)), today)).toBe('today')
  })

  it('в пределах недели — «Ближайшая неделя», дальше — «Позже»', () => {
    expect(groupKeyFor(task(iso(3)), today)).toBe('week')
    expect(groupKeyFor(task(iso(30)), today)).toBe('later')
  })

  it('ИЗВЕСТНОЕ поведение: выполненная с прошлым сроком уезжает в «Сегодня»', () => {
    // Не просрочка (она закрыта) — но и не «сегодня». Дефект виден только на
    // вкладке «Все»: в «Предстоит» выполненных нет вовсе. Зафиксирован
    // тестом, чтобы следующая правка не приняла его за замысел.
    expect(groupKeyFor(task(iso(-180), true), today)).toBe('today')
  })
})

describe('groupTasksByDue', () => {
  it('порядок групп фиксирован, «Без срока» последняя', () => {
    expect(GROUP_ORDER.at(-1)).toBe('nodate')
    const groups = groupTasksByDue([task(null), task(iso(0)), task(iso(-1))])
    expect(groups.map((g) => g.key)).toEqual(GROUP_ORDER)
  })

  it('раскладывает по бакетам и не теряет задач', () => {
    const tasks = [task(null), task(null), task(iso(0)), task(iso(2)), task(iso(-1))]
    const groups = groupTasksByDue(tasks)
    const byKey = Object.fromEntries(groups.map((g) => [g.key, g.items.length]))
    expect(byKey).toEqual({ overdue: 1, today: 1, week: 1, later: 0, nodate: 2 })
    expect(groups.reduce((n, g) => n + g.items.length, 0)).toBe(tasks.length)
  })

  it('пустой вход — все группы пустые, ни одной не пропало', () => {
    const groups = groupTasksByDue([])
    expect(groups).toHaveLength(GROUP_ORDER.length)
    expect(groups.every((g) => g.items.length === 0)).toBe(true)
  })
})
