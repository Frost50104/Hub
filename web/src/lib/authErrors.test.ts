import {
  MissingVerifierError,
  TokenExchangeError,
} from '@signaris/auth-client/browser'
import { describe, expect, it } from 'vitest'

import { authCallbackMessage } from './authErrors'

/**
 * Экран входа — единственное место, где человек видит ошибку auth, и до 0.12
 * он показывал английский текст самой либы. Тест сторожит две вещи разом:
 * что английское наружу не выходит и что ветки не схлопнулись в один текст
 * (совет «попробуйте ещё раз» на сожжённом коде — это и есть петля 03/09.09).
 */
describe('текст экрана незавершённого входа', () => {
  it('кода в адресе нет вовсе — зовёт начать заново, а не повторить', () => {
    const msg = authCallbackMessage(new Error('no authorization code in callback'))
    expect(msg).toBe('Ссылка для входа устарела. Начните вход заново.')
  })

  it('нет записи попытки для state — свой текст вместо английского', () => {
    const msg = authCallbackMessage(new MissingVerifierError())
    expect(msg).toBe('Не удалось завершить вход. Начните вход заново.')
    expect(msg).not.toMatch(/PKCE|verifier/i)
  })

  it('5xx — повтор осмыслен, код мог остаться живым', () => {
    expect(authCallbackMessage(new TokenExchangeError(502))).toBe(
      'auth.signaris.ru не ответил. Попробуйте войти ещё раз.',
    )
  })

  it('4xx — код сожжён, повторять его нечем', () => {
    expect(authCallbackMessage(new TokenExchangeError(400))).toBe(
      'Не удалось завершить вход. Начните вход заново.',
    )
  })

  it('незнакомая ошибка не протекает текстом наружу', () => {
    const msg = authCallbackMessage(new Error('Token exchange failed: 418'))
    expect(msg).toBe('Не удалось завершить вход.')
    expect(msg).not.toContain('418')
  })

  it('распознаёт ошибку по имени — страховка от двух копий либы в бандле', () => {
    const twin = Object.assign(new Error('boom'), {
      name: 'TokenExchangeError',
      status: 503,
    })
    expect(authCallbackMessage(twin)).toBe(
      'auth.signaris.ru не ответил. Попробуйте войти ещё раз.',
    )
  })
})
