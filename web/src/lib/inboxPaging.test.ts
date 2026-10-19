import { describe, expect, it } from 'vitest'

import {
  bucketByAge,
  flattenPages,
  INBOX_FETCH_LIMIT,
  INBOX_PAGE_SIZE,
  pageCursor,
  pageItems,
  WEEK_MS,
} from './inboxPaging'

const rows = (ids: number[]) => ids.map((id) => ({ id }))

describe('pageCursor / pageItems', () => {
  it('51-я строка — признак следующей страницы, курсор — id 50-й', () => {
    const page = rows(Array.from({ length: INBOX_FETCH_LIMIT }, (_, i) => 1000 - i))
    expect(pageCursor(page)).toBe(1000 - (INBOX_PAGE_SIZE - 1))
    expect(pageItems(page)).toHaveLength(INBOX_PAGE_SIZE)
    expect(pageItems(page).at(-1)?.id).toBe(pageCursor(page))
  })

  it('ровно 50 строк — страница последняя, кнопки нет', () => {
    const page = rows(Array.from({ length: INBOX_PAGE_SIZE }, (_, i) => i))
    expect(pageCursor(page)).toBeUndefined()
    expect(pageItems(page)).toHaveLength(INBOX_PAGE_SIZE)
  })

  it('пустая и короткая страницы — без курсора', () => {
    expect(pageCursor([])).toBeUndefined()
    expect(pageCursor(rows([5, 4]))).toBeUndefined()
  })
})

describe('flattenPages', () => {
  it('склеивает страницы в порядке сервера и схлопывает дубль на стыке', () => {
    const first = rows([9, 8, 7])
    const second = rows([7, 6, 5]) // 7 повторилась: курсор взят из устаревшей страницы
    expect(flattenPages([first, second]).map((n) => n.id)).toEqual([9, 8, 7, 6, 5])
  })

  it('не берёт 51-ю строку ни с одной страницы', () => {
    const full = rows(Array.from({ length: INBOX_FETCH_LIMIT }, (_, i) => 100 - i))
    const tail = rows([3, 2, 1])
    const ids = flattenPages([full, tail]).map((n) => n.id)
    expect(ids).toHaveLength(INBOX_PAGE_SIZE + 3)
    expect(ids).not.toContain(100 - INBOX_PAGE_SIZE)
  })

  it('без страниц — пустой список', () => {
    expect(flattenPages([])).toEqual([])
  })
})

describe('bucketByAge', () => {
  const now = Date.parse('2026-10-19T12:00:00Z')
  const at = (ms: number) => ({ created_at: new Date(now - ms).toISOString() })

  it('ровно 7 дней — ещё «Последние 7 дней», на миллисекунду старше — «Раньше»', () => {
    const [recent, older] = bucketByAge([at(WEEK_MS), at(WEEK_MS + 1), at(0)], now)
    expect(recent?.items).toHaveLength(2)
    expect(older?.items).toHaveLength(1)
    expect(recent?.label).toBe('Последние 7 дней')
    expect(older?.label).toBe('Раньше')
  })

  it('сохраняет порядок строк внутри группы и всегда отдаёт обе группы', () => {
    const groups = bucketByAge([at(10), at(5), at(WEEK_MS * 2)], now)
    expect(groups.map((g) => g.key)).toEqual(['7d', 'older'])
    expect(groups[0]?.items.map((n) => n.created_at)).toEqual([
      at(10).created_at,
      at(5).created_at,
    ])
    expect(bucketByAge([], now).every((g) => g.items.length === 0)).toBe(true)
  })
})
