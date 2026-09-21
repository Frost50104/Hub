import { describe, expect, it } from 'vitest'

import { extractErrorDetail } from './errors'
import { NBSP } from './typography'

/** Ошибка в форме axios: `message` от транспорта + ответ сервера. */
const axiosError = (detail: unknown, message = 'Request failed with status code 422') =>
  Object.assign(new Error(message), { response: { data: { detail } } })

describe('extractErrorDetail', () => {
  it('строковый detail сервера отдаётся как есть', () => {
    expect(extractErrorDetail(axiosError('Колонка не найдена', 'x'))).toBe('Колонка не найдена')
  })

  it('слишком длинное поле → русский текст с лимитом вместо «status code 422»', () => {
    // Ровно то, что FastAPI отдал на комментарий в 9 279 символов (ОС 21.09).
    const err = axiosError([
      {
        type: 'string_too_long',
        loc: ['body', 'body'],
        msg: 'String should have at most 4000 characters',
        ctx: { max_length: 4000 },
      },
    ])
    expect(extractErrorDetail(err)).toBe(`Слишком длинный текст: не больше 4${NBSP}000 символов`)
  })

  it('string_too_long ищется по всему списку, а не только в первой строке', () => {
    const err = axiosError([
      { type: 'missing', loc: ['body', 'title'], msg: 'Field required' },
      { type: 'string_too_long', loc: ['body', 'description'], ctx: { max_length: 20_000 } },
    ])
    expect(extractErrorDetail(err)).toBe(`Слишком длинный текст: не больше 20${NBSP}000 символов`)
  })

  it('иной список ошибок → общий русский текст, а не английский msg pydantic', () => {
    const err = axiosError([{ type: 'missing', loc: ['body', 'title'], msg: 'Field required' }])
    expect(extractErrorDetail(err)).toBe('Сервер не принял данные — проверьте заполнение полей')
  })

  it('без ответа сервера — сообщение транспорта; без него — «Неизвестная ошибка»', () => {
    expect(extractErrorDetail(new Error('Network Error'))).toBe('Network Error')
    expect(extractErrorDetail(axiosError([], 'Network Error'))).toBe('Network Error')
    expect(extractErrorDetail(null)).toBe('Неизвестная ошибка')
    expect(extractErrorDetail({})).toBe('Неизвестная ошибка')
  })
})
