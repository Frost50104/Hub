import { describe, expect, it } from 'vitest'

import { inboxCounter, inboxEmpty } from './inboxView'

// Неразрывный пробел кодом, а не литералом: глазами он неотличим от
// обычного, и тест падал бы с «expected 'X' to be 'X'».
const NBSP = '\u00a0'

describe('inboxCounter', () => {
  it('склоняет непрочитанные', () => {
    expect(inboxCounter(160)).toBe(`160${NBSP}непрочитанных`)
    expect(inboxCounter(1)).toBe(`1${NBSP}непрочитанное`)
    expect(inboxCounter(3)).toBe(`3${NBSP}непрочитанных`)
  })

  it('без непрочитанных не называет числа', () => {
    // Общего счётчика уведомлений сервер не отдаёт, а длина списка упирается
    // в лимит ручки (50) — любое число здесь было бы неверным.
    expect(inboxCounter(0)).toBe('Всё прочитано')
  })
})

describe('inboxEmpty', () => {
  it('различает «разобрано» и «не приходило»', () => {
    expect(inboxEmpty(true).title).toBe('Всё прочитано')
    expect(inboxEmpty(false).title).toBe('Здесь пока тихо')
  })

  it('из окна непрочитанных подсказывает, где искать прочитанные', () => {
    expect(inboxEmpty(true).body).toContain('Все')
  })
})
