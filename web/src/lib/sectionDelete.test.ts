import { describe, expect, it } from 'vitest'

import { describeSectionContents, sectionContents } from './sectionDelete'

describe('sectionDelete', () => {
  const materials = [
    { section_id: 's1', status: 'published' },
    { section_id: 's1', status: 'draft' },
    { section_id: 's1', status: 'archived' },
    { section_id: 's2', status: 'published' },
    { section_id: null, status: 'published' },
  ]
  const sections = [
    { id: 's1', parent_id: null },
    { id: 's2', parent_id: 's1' },
  ]

  it('считает материалы по статусам и подразделы', () => {
    expect(sectionContents('s1', materials, sections)).toEqual({
      materials: 3,
      published: 1,
      drafts: 1,
      archived: 1,
      children: 1,
    })
    expect(sectionContents('s2', materials, sections).children).toBe(0)
  })

  it('описывает содержимое по-русски; пустой раздел — null', () => {
    const text = describeSectionContents(sectionContents('s1', materials, sections)) ?? ''
    // plural() вставляет неразрывный пробел между числом и словом — сверяем фрагментами.
    for (const part of ['материала', 'опубликовано 1', 'черновиков 1', 'в архиве 1', 'подраздел']) {
      expect(text).toContain(part)
    }
    expect(text.endsWith('останутся в библиотеке без раздела.')).toBe(true)
    expect(describeSectionContents(sectionContents('s3', materials, sections))).toBeNull()
  })
})
