import { describe, expect, it } from 'vitest'

import {
  favoriteKey,
  favoriteTypesPresent,
  isFavorite,
  toggleFavoriteKey,
} from './favorites'

describe('favoriteKey', () => {
  it('тип и id склеиваются одинаково во всех списках', () => {
    expect(favoriteKey('course', 'abc')).toBe('course:abc')
  })

  it('один id в разных типах — разные ключи', () => {
    // id объектов приходят из разных таблиц и в теории могут совпасть; без
    // типа звезда загорелась бы у чужого объекта.
    expect(favoriteKey('course', 'x')).not.toBe(favoriteKey('product', 'x'))
  })
})

describe('isFavorite', () => {
  it('пустой набор (профиля нет / ещё грузится) — не падает', () => {
    expect(isFavorite(undefined, 'course', 'x')).toBe(false)
  })

  it('находит по паре тип+id', () => {
    const keys = new Set(['course:x'])
    expect(isFavorite(keys, 'course', 'x')).toBe(true)
    expect(isFavorite(keys, 'product', 'x')).toBe(false)
  })
})

describe('toggleFavoriteKey', () => {
  it('добавляет и убирает', () => {
    const empty = new Set<string>()
    const added = toggleFavoriteKey(empty, 'course', 'x')
    expect([...added]).toEqual(['course:x'])
    expect([...toggleFavoriteKey(added, 'course', 'x')]).toEqual([])
  })

  it('возвращает новый Set — иначе звезда не перерисуется до ответа сервера', () => {
    const keys = new Set<string>()
    expect(toggleFavoriteKey(keys, 'course', 'x')).not.toBe(keys)
    expect(keys.size).toBe(0)
  })
})

describe('favoriteTypesPresent', () => {
  it('только те типы, что реально есть, в порядке словаря', () => {
    expect(
      favoriteTypesPresent([
        { object_type: 'product' },
        { object_type: 'library_material' },
        { object_type: 'product' },
      ]),
    ).toEqual(['library_material', 'product'])
  })

  it('пустой список — пустые фильтры', () => {
    expect(favoriteTypesPresent([])).toEqual([])
  })
})
