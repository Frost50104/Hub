import { describe, expect, it } from 'vitest'

import {
  allIds,
  bulkReadToast,
  chunkIds,
  pruneSelection,
  READ_STATE_MAX,
  selectAllLabel,
  selectionLabel,
  toggleId,
} from './inboxSelection'

const NBSP = ' '

describe('toggleId / allIds / pruneSelection', () => {
  it('добавляет и снимает, не трогая исходное множество', () => {
    const base = new Set([1, 2])
    const added = toggleId(base, 3)
    expect([...added]).toEqual([1, 2, 3])
    expect([...toggleId(added, 2)]).toEqual([1, 3])
    expect([...base]).toEqual([1, 2])
  })

  it('«выбрать все» берёт все загруженные id', () => {
    expect([...allIds([{ id: 7 }, { id: 3 }])]).toEqual([7, 3])
  })

  it('оставляет в выборе только то, что ещё загружено', () => {
    const picked = new Set([1, 2, 3])
    expect([...pruneSelection(picked, [{ id: 2 }, { id: 3 }, { id: 9 }])]).toEqual([2, 3])
    expect(pruneSelection(picked, []).size).toBe(0)
  })
})

describe('chunkIds', () => {
  it('режет под потолок ручки', () => {
    const ids = Array.from({ length: READ_STATE_MAX * 2 + 7 }, (_, i) => i)
    const chunks = chunkIds(ids)
    expect(chunks.map((c) => c.length)).toEqual([READ_STATE_MAX, READ_STATE_MAX, 7])
    expect(chunks.flat()).toEqual(ids)
  })

  it('пусто — ни одного запроса', () => {
    expect(chunkIds([])).toEqual([])
  })
})

describe('подписи панели', () => {
  it('считает выбранные и называет число загруженных', () => {
    expect(selectionLabel(0)).toBe('Ничего не выбрано')
    expect(selectionLabel(12)).toBe('Выбрано 12')
    expect(selectAllLabel(50, false)).toBe('Выбрать все (50)')
    expect(selectAllLabel(50, true)).toBe('Снять выбор')
  })

  it('тост — по числу реально изменённых строк', () => {
    expect(bulkReadToast(12, true)).toBe(`Прочитано 12${NBSP}уведомлений`)
    expect(bulkReadToast(1, true)).toBe(`Прочитано 1${NBSP}уведомление`)
    expect(bulkReadToast(3, false)).toBe(`Отмечено как непрочитанное: 3${NBSP}уведомления`)
    expect(bulkReadToast(0, true)).toBe('Все выбранные уже прочитаны')
    expect(bulkReadToast(0, false)).toBe('Все выбранные уже непрочитаны')
  })
})
