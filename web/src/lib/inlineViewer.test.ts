import { describe, expect, it } from 'vitest'

import { hasTextPreview, inlineViewerKind, materialPrimaryAction } from './inlineViewer'

const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

describe('inlineViewerKind', () => {
  it('показывает PDF своим вьювером', () => {
    expect(inlineViewerKind('application/pdf')).toBe('pdf')
  })

  it('показывает растровые картинки', () => {
    for (const mime of ['image/png', 'image/jpeg', 'image/webp', 'image/gif']) {
      expect(inlineViewerKind(mime)).toBe('image')
    }
  })

  it('НЕ показывает svg инлайн — это исполняемый документ', () => {
    expect(inlineViewerKind('image/svg+xml')).toBeNull()
  })

  it('офисные форматы инлайн не открываются', () => {
    expect(inlineViewerKind(DOCX)).toBeNull()
    expect(inlineViewerKind('text/html')).toBeNull()
    expect(inlineViewerKind(null)).toBeNull()
    expect(inlineViewerKind(undefined)).toBeNull()
  })
})

describe('materialPrimaryAction — кнопка называется по тому, что произойдёт', () => {
  it('ссылка / инлайн / скачивание', () => {
    expect(materialPrimaryAction('link', null)).toEqual({ mode: 'link', label: 'Открыть ссылку' })
    expect(materialPrimaryAction('file', 'application/pdf').mode).toBe('inline')
    expect(materialPrimaryAction('file', 'image/png').label).toBe('Открыть документ')
    const docx = materialPrimaryAction('file', DOCX)
    expect(docx.mode).toBe('download')
    expect(docx.label).toBe('Скачать файл')
    expect(docx.hint).toContain('Ознакомлен')
  })

  it('текстовый предпросмотр — только docx/xlsx', () => {
    expect(hasTextPreview(DOCX)).toBe(true)
    expect(hasTextPreview(XLSX)).toBe(true)
    expect(hasTextPreview('application/msword')).toBe(false)
    expect(hasTextPreview('application/pdf')).toBe(false)
    expect(hasTextPreview(null)).toBe(false)
  })
})
