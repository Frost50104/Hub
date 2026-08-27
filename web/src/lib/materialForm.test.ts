import { describe, expect, it } from 'vitest'

import { canPublishMaterial, canSaveMaterial, type MaterialFormState } from './materialForm'

const s = (over: Partial<MaterialFormState> = {}): MaterialFormState => ({
  title: 'Регламент',
  kind: 'file',
  url: '',
  hasFile: true,
  ...over,
})

describe('canSaveMaterial', () => {
  it('название обязательно', () => {
    expect(canSaveMaterial(s({ title: '   ' }))).toBe(false)
  })

  it('ссылке нужен http(s)-адрес', () => {
    expect(canSaveMaterial(s({ kind: 'link', url: 'ftp://x' }))).toBe(false)
    expect(canSaveMaterial(s({ kind: 'link', url: 'https://x.ru/a' }))).toBe(true)
  })

  it('файловый материал сохраняется черновиком и без файла', () => {
    // Черновик без файла — законное состояние: файл догружают из карточки.
    expect(canSaveMaterial(s({ hasFile: false }))).toBe(true)
  })
})

describe('canPublishMaterial', () => {
  it('файловый материал без файла публиковать нельзя — сервер ответит 422', () => {
    expect(canPublishMaterial(s({ hasFile: false }))).toBe(false)
  })

  it('с файлом — можно', () => {
    expect(canPublishMaterial(s())).toBe(true)
  })

  it('ссылке файл не нужен', () => {
    expect(canPublishMaterial(s({ kind: 'link', url: 'https://x.ru', hasFile: false }))).toBe(true)
  })

  it('невалидную форму публиковать нельзя ни при каком файле', () => {
    expect(canPublishMaterial(s({ title: '' }))).toBe(false)
  })
})
