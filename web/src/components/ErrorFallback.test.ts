import { describe, expect, it } from 'vitest'

import { describeError } from './ErrorFallback'

/**
 * Текст на экране сбоя — единственный канал диагностики, пока Sentry в Hub не
 * подключён: 27.08 сотрудник прислал скриншот этого экрана, и выяснить причину
 * было нечем. Поэтому у сборки текста есть тесты.
 */
describe('describeError', () => {
  it('показывает имя, сообщение и адрес — «упало где-то» не диагноз', () => {
    const out = describeError(new Error('boom'), '/my?x=1')
    expect(out).toContain('Error: boom')
    expect(out).toContain('/my?x=1')
  })

  it('берёт первую строку стека: в проде он минифицирован, но чанк виден', () => {
    const err = new Error('boom')
    err.stack = 'Error: boom\n    at Xy (/assets/index-Abc123.js:1:99)\n    at z'
    expect(describeError(err, '/')).toContain('index-Abc123.js')
  })

  it('переживает не-Error: строку, объект и null', () => {
    expect(describeError('просто строка', '/')).toContain('просто строка')
    expect(describeError({ code: 42 }, '/')).toContain('42')
    expect(describeError(null, '/')).toBeNull()
    expect(describeError(undefined, '/')).toBeNull()
  })

  it('циклический объект не роняет сам экран сбоя', () => {
    // Иначе обработчик ошибки падал бы там, где должен объяснять ошибку.
    const cyclic: Record<string, unknown> = {}
    cyclic.self = cyclic
    expect(() => describeError(cyclic, '/')).not.toThrow()
  })
})
