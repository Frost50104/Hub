import { describe, expect, it } from 'vitest'

import { storeAssignable, storeLabel } from './storeState'

const AT = '2026-10-19T10:00:00Z'

describe('состояние точки для пикеров (0065)', () => {
  it('новое назначается только на работающую точку', () => {
    expect(storeAssignable({ archived_at: null })).toBe(true)
    expect(storeAssignable({ archived_at: null, suspended_at: null })).toBe(true)
    expect(storeAssignable({ archived_at: null, suspended_at: AT })).toBe(false)
    expect(storeAssignable({ archived_at: AT })).toBe(false)
  })

  it('старый бэкенд поля не шлёт — точка работает', () => {
    expect(storeAssignable({ archived_at: null, suspended_at: undefined })).toBe(true)
  })

  it('подпись выбранного: архив важнее паузы', () => {
    expect(storeLabel({ name: 'Приморская 14', archived_at: null })).toBe('Приморская 14')
    expect(storeLabel({ name: 'Приморская 14', archived_at: null, suspended_at: AT })).toBe('Приморская 14 (приостановлена)')
    expect(storeLabel({ name: 'Приморская 14', archived_at: AT, suspended_at: AT })).toBe('Приморская 14 (архив)')
  })
})
