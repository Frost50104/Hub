import { describe, expect, it } from 'vitest'

import { inlineViewerKind } from './inlineViewer'

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

  it('остальное остаётся скачиванием', () => {
    expect(inlineViewerKind('application/vnd.openxmlformats-officedocument.wordprocessingml.document')).toBeNull()
    expect(inlineViewerKind('text/html')).toBeNull()
    expect(inlineViewerKind(null)).toBeNull()
    expect(inlineViewerKind(undefined)).toBeNull()
  })
})
