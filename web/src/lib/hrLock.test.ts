import { describe, expect, it } from 'vitest'

import {
  hrLineText,
  hrSyncToastLine,
  hrValueLabel,
  isHrFrozenError,
  omitHrFields,
  returnsByItself,
  type HrView,
} from './hrLock'

// Не из `./learn`: тот тянет API-клиент с `window`, а vitest здесь без jsdom.
const ORG_ROLE_LABEL = {
  employee: 'Сотрудник',
  tu: 'Территориальный управляющий',
  franchisee_owner: 'Франчайзи',
  office: 'Офис',
} as const

const view = (over: Partial<HrView> = {}): HrView => ({
  frozen: true,
  window: false,
  state: 'synced',
  synced_at: '2026-09-25T11:05:00Z',
  edit_url: 'https://auth.signaris.ru/admin/employees',
  org_url: 'https://auth.signaris.ru/admin/org',
  ...over,
})

describe('hrLock', () => {
  it('строка говорит правду о том, почему поле закрыто', () => {
    const synced = hrLineText(view())
    expect(synced.text).toBe('Кадровые данные ведутся в auth')
    expect(synced.updated).toMatch(/^обновлено в \d{2}:\d{2}$/)
    expect(hrLineText(view({ state: 'window' })).text).toContain('перенос')
    expect(hrLineText(view({ state: 'blocked' })).text).toContain('ждут подтверждения')
    expect(hrLineText(view({ state: 'paused' })).text).toContain('не включено')
    expect(hrLineText(view({ state: 'stale' })).text).toContain('давно не получал')
    expect(hrLineText(view({ state: 'stale', synced_at: null })).text).not.toContain('последний')
  })

  it('кадровые поля не уходят в запрос, телефон и права — уходят', () => {
    const out = omitHrFields({
      phone: '+7',
      content_role: 'author',
      position_id: 'p',
      org_role: 'tu',
      manager_profile_id: 'm',
      hired_at: null,
    })
    expect(out).toEqual({ phone: '+7', content_role: 'author' })
  })

  it('отказ заморозки узнаётся по тексту сервера', () => {
    expect(isHrFrozenError('Кадровые данные ведутся в auth — поменяйте их там')).toBe(true)
    expect(isHrFrozenError('Закреплённые точки ведутся в auth. Остальные…')).toBe(true)
    expect(isHrFrozenError('Идёт перенос кадровых данных в auth — правка временно закрыта')).toBe(true)
    expect(isHrFrozenError('Справочник ведётся в auth — поменяйте его там')).toBe(true)
    expect(isHrFrozenError('Карточка не найдена')).toBe(false)
    expect(isHrFrozenError(null)).toBe(false)
  })

  it('тост синка: пробный прогон, применено, остановлено предохранителем', () => {
    expect(hrSyncToastLine(null)).toBeNull()
    expect(
      hrSyncToastLine({ mode: 'report', cards: { change: ['a', 'b'] }, new_cards: [] }),
    ).toBe('Кадровые данные из auth (пробный прогон): изменений карточек 2')
    expect(
      hrSyncToastLine({ mode: 'apply', cards: { change: ['a'], fill: ['b'] }, new_cards: ['c'] }),
    ).toBe('Кадровые данные из auth применены: изменено карточек 2, новых карточек 1')
    expect(hrSyncToastLine({ mode: 'blocked' })).toContain('больше порога')
    expect(hrSyncToastLine({ mode: 'idle' })).toBeNull()
  })

  it('подписи значений в диалоге предохранителя', () => {
    expect(hrValueLabel('org_role', 'tu', ORG_ROLE_LABEL)).toBe('Территориальный управляющий')
    expect(hrValueLabel('hired_at', '2024-03-01', ORG_ROLE_LABEL)).toBe('01.03.2024')
    expect(hrValueLabel('position_id', 'Бариста', ORG_ROLE_LABEL)).toBe('Бариста')
    expect(hrValueLabel('position_id', null, ORG_ROLE_LABEL)).toBe('—')
  })

  it('отключённая в auth карточка возвращается сама — только при заморозке и с входом', () => {
    const card = { status: 'archived', archive_reason: 'auth_deactivated', employee_id: 'e' }
    expect(returnsByItself(card, view())).toBe(true)
    expect(returnsByItself(card, null)).toBe(false) // откат: правка снова в Hub
    expect(returnsByItself({ ...card, employee_id: null }, view())).toBe(false)
    expect(returnsByItself({ ...card, archive_reason: 'manual' }, view())).toBe(false)
  })
})
