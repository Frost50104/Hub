import { describe, expect, it } from 'vitest'

import { nextName } from './renameDraft'

describe('nextName', () => {
  it.each([
    ['', 'пусто'],
    ['   ', 'одни пробелы'],
    ['Отдел', 'совпадает с текущим'],
    [' Отдел ', 'совпадает с точностью до пробелов'],
  ])('%o (%s) — запрос не уходит', (draft) => {
    expect(nextName(draft, 'Отдел')).toBeNull()
  })

  it('новое имя триммится', () => {
    expect(nextName('  Новое  ', 'Отдел')).toBe('Новое')
  })

  it('текущее имя с пробелами по краям не мешает переименованию', () => {
    expect(nextName('Новое', '  Отдел  ')).toBe('Новое')
  })
})
