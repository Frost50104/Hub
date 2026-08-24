import { describe, expect, it } from 'vitest'

import {
  emptyPickReason,
  emptyPickText,
  type DimensionCounts,
  type PickedCondition,
} from './audienceHints'

const counts: DimensionCounts = {
  position_ids: { seller: 2 },
  store_ids: { nevskaya: 3 },
  org_roles: { office: 1, employee: 6 },
}

function cond(key: string, id: string, dim: string, value: string): PickedCondition {
  return { key, id, dimensionLabel: dim, valueLabel: value }
}

describe('emptyPickReason', () => {
  it('называет измерение, за значением которого никого нет', () => {
    const reason = emptyPickReason(
      [cond('position_ids', 'admin', 'Должность', 'Администратор')],
      counts,
    )
    expect(reason).toEqual({
      kind: 'value',
      dimensionLabel: 'Должность',
      valueLabels: ['Администратор'],
    })
    expect(emptyPickText(reason!)).toBe(
      'Ни один активный сотрудник не подходит: Должность — «Администратор».',
    )
  })

  it('несколько пустых значений одного измерения перечисляются', () => {
    const reason = emptyPickReason(
      [
        cond('position_ids', 'admin', 'Должность', 'Администратор'),
        cond('position_ids', 'mentor', 'Должность', 'Наставник'),
      ],
      counts,
    )
    expect(reason).toEqual({
      kind: 'value',
      dimensionLabel: 'Должность',
      valueLabels: ['Администратор', 'Наставник'],
    })
  })

  it('одно живое значение в измерении снимает с него подозрение', () => {
    const reason = emptyPickReason(
      [
        cond('position_ids', 'admin', 'Должность', 'Администратор'),
        cond('position_ids', 'seller', 'Должность', 'Продавец'),
      ],
      counts,
    )
    // Внутри измерения значения — ИЛИ: раз продавцы есть, должность не виновата.
    expect(reason).toBeNull()
  })

  it('когда каждое измерение живое — виновато пересечение', () => {
    const reason = emptyPickReason(
      [
        cond('position_ids', 'seller', 'Должность', 'Продавец'),
        cond('store_ids', 'nevskaya', 'Магазин', 'Невская, 3'),
      ],
      counts,
    )
    expect(reason).toEqual({
      kind: 'intersection',
      dimensionLabels: ['Должность', 'Магазин'],
    })
    expect(emptyPickText(reason!)).toBe(
      'Нет сотрудников, у которых одновременно совпадают должность и магазин.',
    )
  })

  it('конкретный сотрудник виноватым не бывает', () => {
    expect(
      emptyPickReason([cond('profile_ids', 'u1', 'Сотрудник', 'Ирина')], counts),
    ).toBeNull()
  })

  it('без счётчиков и без условий молчит', () => {
    expect(emptyPickReason([], counts)).toBeNull()
    expect(
      emptyPickReason([cond('position_ids', 'admin', 'Должность', 'Админ')], undefined),
    ).toBeNull()
  })
})
