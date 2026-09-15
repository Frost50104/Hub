import { describe, expect, it } from 'vitest'

import { shouldOfferUpdate } from './appVersion'

const LOADED = '176a3e1-20260915-224708'
const NEWER = 'dc47983-20260916-101500'

describe('shouldOfferUpdate', () => {
  it('версии совпали — предлагать нечего', () => {
    // Ровно случай владельца на десктопе: в настройках стояла та же версия,
    // что на сервере, и отсутствие баннера там было правильным.
    expect(shouldOfferUpdate(LOADED, LOADED)).toBe(false)
  })

  it('на сервере другая версия — предлагаем', () => {
    expect(shouldOfferUpdate(LOADED, NEWER)).toBe(true)
  })

  it('версию узнать не удалось — молчим', () => {
    // Офлайн или дев-стенд без version.json. Позвать обновляться на пустом
    // месте значит подтолкнуть человека потерять несохранённое.
    expect(shouldOfferUpdate(LOADED, null)).toBe(false)
  })

  it('отложенную версию не показываем, а следующую — показываем', () => {
    expect(shouldOfferUpdate(LOADED, NEWER, NEWER)).toBe(false)
    expect(shouldOfferUpdate(LOADED, 'ещё-новее', NEWER)).toBe(true)
  })

  it('отложили одну, а сервер откатился на нашу же — молчим', () => {
    // Откат выката: сервер снова отдаёт то, что у нас загружено.
    expect(shouldOfferUpdate(LOADED, LOADED, NEWER)).toBe(false)
  })
})
