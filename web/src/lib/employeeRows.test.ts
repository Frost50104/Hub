import { describe, expect, it } from 'vitest'

import type { AuthInvitation, EmployeeProfile } from './learn'
import {
  employeeRowsCaption,
  invitedCount,
  matchesRowFilter,
  mergeEmployeeRows,
} from './employeeRows'

const person = (id: string, name: string, auth_state: string | null): EmployeeProfile =>
  ({ id, full_name: name, auth_state }) as unknown as EmployeeProfile

const inv = (id: string, email: string, full_name: string | null = null): AuthInvitation => ({
  id,
  email,
  full_name,
  role: 'member',
  expires_at: null,
})

describe('mergeEmployeeRows', () => {
  it('ставит приглашения в общий алфавитный порядок, а не отдельным блоком', () => {
    const rows = mergeEmployeeRows(
      [person('1', 'Яковлев Пётр', 'active'), person('2', 'Абрамов Иван', 'active')],
      [inv('i1', 'b@t.ru', 'Борисова Анна')],
    )
    expect(rows.map((r) => r.name)).toEqual([
      'Абрамов Иван',
      'Борисова Анна',
      'Яковлев Пётр',
    ])
  })

  it('без ФИО показывает почту', () => {
    const [row] = mergeEmployeeRows([], [inv('i1', 'natzamik@gmail.com')])
    expect(row?.name).toBe('natzamik@gmail.com')
  })

  it('порядок устойчив у полных тёзок — иначе список прыгает между ререндерами', () => {
    const a = mergeEmployeeRows([person('b', 'Иванов Иван', null), person('a', 'Иванов Иван', null)], [])
    const b = mergeEmployeeRows([person('a', 'Иванов Иван', null), person('b', 'Иванов Иван', null)], [])
    expect(a.map((r) => r.id)).toEqual(b.map((r) => r.id))
  })
})

describe('matchesRowFilter', () => {
  const rows = mergeEmployeeRows(
    [
      person('1', 'Активный Пётр', 'active'),
      person('2', 'Приглашённый Иван', 'invited'),
      person('3', 'Невходивший Олег', 'not_logged_in'),
    ],
    [inv('i1', 'new@t.ru', 'Безкарточки Анна')],
  )

  it('«Все» пропускает всех, включая приглашения', () => {
    expect(rows.filter((r) => matchesRowFilter('all', r))).toHaveLength(4)
  })

  it('приглашение без карточки считается и «без учётки»', () => {
    const names = rows.filter((r) => matchesRowFilter('no_account', r)).map((r) => r.name)
    expect(names).toContain('Безкарточки Анна')
    expect(names).toContain('Приглашённый Иван')
  })

  it('чип «Приглашены» собирает оба вида строк', () => {
    // 62 карточки с бейджем «Приглашён(а)» + 7 приглашений без карточки — на
    // проде это ровно те 69, что показывал прежний блок.
    expect(invitedCount(rows)).toBe(2)
  })

  it('«Не входили» приглашения НЕ подхватывает: человек ещё и учётку не завёл', () => {
    const names = rows.filter((r) => matchesRowFilter('not_logged_in', r)).map((r) => r.name)
    expect(names).toEqual(['Невходивший Олег'])
  })
})

describe('employeeRowsCaption', () => {
  it('при фильтре говорит «отобрано» и не советует уточнить поиск', () => {
    expect(employeeRowsCaption(7, 264, { filtered: true })).toBe('Отобрано: 7 из 264')
  })

  it('без фильтра и с обрезкой — прежний совет', () => {
    expect(employeeRowsCaption(100, 264, { filtered: false })).toContain('Показаны 100 из 264')
  })

  it('всё показано — просто итог', () => {
    expect(employeeRowsCaption(264, 264, { filtered: false })).toBe('Всего: 264')
  })
})
