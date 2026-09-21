import { describe, expect, it } from 'vitest'

import { COMMENT_HINT_FROM, COMMENT_MAX_LENGTH, commentLength, commentLengthHint } from './commentDraft'
import { NBSP } from './typography'

const text = (n: number) => 'я'.repeat(n)

describe('длина комментария задачи', () => {
  it('лимит — зеркало сервера, счётчик — с 90 %', () => {
    expect(COMMENT_MAX_LENGTH).toBe(20_000)
    expect(COMMENT_HINT_FROM).toBe(18_000)
  })

  it('обычный комментарий подсказки не получает', () => {
    expect(commentLengthHint('').show).toBe(false)
    expect(commentLengthHint(text(935)).show).toBe(false)
    expect(commentLengthHint(text(9_279)).show).toBe(false)
    expect(commentLengthHint(text(COMMENT_HINT_FROM - 1)).show).toBe(false)
  })

  it('у края лимита — счётчик, отправка ещё разрешена', () => {
    const at = commentLengthHint(text(18_200))
    expect(at).toEqual({ show: true, over: false, text: `18${NBSP}200 / 20${NBSP}000` })
    expect(commentLengthHint(text(COMMENT_MAX_LENGTH)).over).toBe(false)
  })

  it('сверх лимита — блокировка и причина с обоими числами', () => {
    const over = commentLengthHint(text(21_034))
    expect(over.over).toBe(true)
    expect(over.text).toContain(`20${NBSP}000`)
    expect(over.text).toContain(`21${NBSP}034`)
    expect(commentLengthHint(text(COMMENT_MAX_LENGTH + 1)).over).toBe(true)
  })

  it('считает как сервер: по обрезанному тексту и кодовыми точками', () => {
    // Пробелы по краям не уходят на сервер — и в лимит не считаются.
    expect(commentLength(`  ${text(10)}\n\n`)).toBe(10)
    // Эмодзи — одна кодовая точка (len() в Python), хотя в JS .length = 2.
    expect('🪿'.length).toBe(2)
    expect(commentLength('🪿')).toBe(1)
    expect(commentLengthHint('🪿'.repeat(COMMENT_MAX_LENGTH)).over).toBe(false)
  })
})
