import { describe, expect, it } from 'vitest'

import { TIMEOUT, withTimeout } from './withTimeout'

describe('withTimeout', () => {
  it('успевший промис отдаёт своё значение', async () => {
    await expect(withTimeout(Promise.resolve('готово'), 50)).resolves.toBe('готово')
  })

  it('зависший отдаёт метку времени, а не висит вечно', async () => {
    // Ровно поведение `registration.update()` в Safari: промис, который
    // никогда не резолвится (замер 16.09 — 15 с без ответа).
    const вечный = new Promise<string>(() => {})
    await expect(withTimeout(вечный, 10)).resolves.toBe(TIMEOUT)
  })

  it('отказ пробрасывается, а не превращается в таймаут', async () => {
    // Иначе офлайн-клик радостно сообщал бы «у вас последняя версия».
    await expect(withTimeout(Promise.reject(new Error('офлайн')), 50)).rejects.toThrow('офлайн')
  })
})
