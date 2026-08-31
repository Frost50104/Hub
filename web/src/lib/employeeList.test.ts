import { describe, expect, it, vi } from 'vitest'

import {
  EMPLOYEE_MAX_PAGES,
  EMPLOYEE_PAGE_SIZE,
  collectEmployees,
  employeeListCaption,
  employeeTruncationNote,
} from './employeeList'

const person = (n: number) => ({ id: `id-${n}` })
const people = (n: number, from = 0) =>
  Array.from({ length: n }, (_, i) => person(from + i))

describe('collectEmployees', () => {
  it('одной короткой страницей — один запрос', async () => {
    const fetchPage = vi.fn(async () => ({ items: people(149), total: 149 }))
    const res = await collectEmployees(fetchPage)
    expect(res.items).toHaveLength(149)
    expect(res.total).toBe(149)
    expect(fetchPage).toHaveBeenCalledTimes(1)
  })

  it('добирает следующую страницу и сохраняет порядок сервера', async () => {
    const fetchPage = vi.fn(async (_l: number, offset: number) =>
      offset === 0
        ? { items: people(EMPLOYEE_PAGE_SIZE), total: EMPLOYEE_PAGE_SIZE + 3 }
        : { items: people(3, EMPLOYEE_PAGE_SIZE), total: EMPLOYEE_PAGE_SIZE + 3 },
    )
    const res = await collectEmployees(fetchPage)
    expect(res.items).toHaveLength(EMPLOYEE_PAGE_SIZE + 3)
    expect(res.items[0]?.id).toBe('id-0')
    expect(res.items.at(-1)?.id).toBe(`id-${EMPLOYEE_PAGE_SIZE + 2}`)
  })

  it('не зацикливается, если total больше отдаваемого', async () => {
    // Ровно тот случай, ради которого останов двойной: сервер обещает 10 000,
    // а отдаёт полную страницу каждый раз. Без выхода по пределу — вечный цикл.
    const fetchPage = vi.fn(async (_l: number, offset: number) => ({
      items: people(EMPLOYEE_PAGE_SIZE, offset),
      total: 10_000,
    }))
    const res = await collectEmployees(fetchPage)
    expect(fetchPage).toHaveBeenCalledTimes(EMPLOYEE_MAX_PAGES)
    expect(res.items).toHaveLength(EMPLOYEE_PAGE_SIZE * EMPLOYEE_MAX_PAGES)
    expect(res.total).toBe(10_000)
  })

  it('дедуплицирует пересечение страниц', async () => {
    // Между запросами кого-то завели, границы сдвинулись, и первый со второй
    // страницы уже был на первой.
    const fetchPage = vi.fn(async (_l: number, offset: number) =>
      offset === 0
        ? { items: people(EMPLOYEE_PAGE_SIZE), total: EMPLOYEE_PAGE_SIZE + 2 }
        : { items: people(2, EMPLOYEE_PAGE_SIZE - 1), total: EMPLOYEE_PAGE_SIZE + 2 },
    )
    const res = await collectEmployees(fetchPage)
    expect(res.items).toHaveLength(EMPLOYEE_PAGE_SIZE + 1)
    expect(new Set(res.items.map((p) => p.id)).size).toBe(res.items.length)
  })
})

describe('подписи', () => {
  it('полный список — прежнее «Всего»', () => {
    expect(employeeListCaption(149, 149)).toBe('Всего: 149')
    expect(employeeTruncationNote(149, 149)).toBeNull()
  })

  it('обрезанный — говорит об этом обоими способами', () => {
    // Экран не имеет права показывать 100 строк под надписью «Всего: 149».
    expect(employeeListCaption(100, 149)).toContain('Показаны 100 из 149')
    expect(employeeTruncationNote(100, 149)).toContain('Показаны 100 из 149')
  })
})
