import { plural } from '@/lib/typography'

export interface SectionContents {
  materials: number
  published: number
  drafts: number
  archived: number
  children: number
}

/** Что лежит в разделе — для диалога удаления (любой статус блокирует строгое удаление). */
export function sectionContents(
  sectionId: string,
  materials: readonly { section_id: string | null; status: string }[],
  sections: readonly { id: string; parent_id?: string | null }[],
): SectionContents {
  let published = 0
  let drafts = 0
  let archived = 0
  for (const m of materials) {
    if (m.section_id !== sectionId) continue
    if (m.status === 'published') published += 1
    else if (m.status === 'archived') archived += 1
    else drafts += 1
  }
  const children = sections.filter((s) => s.parent_id === sectionId).length
  return { materials: published + drafts + archived, published, drafts, archived, children }
}

/** «5 материалов (опубликовано 3 · черновиков 1 · в архиве 1) и 1 подраздел останутся…» */
export function describeSectionContents(c: SectionContents): string | null {
  if (!c.materials && !c.children) return null
  const parts: string[] = []
  if (c.materials) {
    const breakdown = [
      c.published ? `опубликовано ${c.published}` : null,
      c.drafts ? `черновиков ${c.drafts}` : null,
      c.archived ? `в архиве ${c.archived}` : null,
    ]
      .filter(Boolean)
      .join(' · ')
    parts.push(`${plural(c.materials, 'материал', 'материала', 'материалов')} (${breakdown})`)
  }
  if (c.children) parts.push(plural(c.children, 'подраздел', 'подраздела', 'подразделов'))
  return `${parts.join(' и ')} останутся в библиотеке без раздела.`
}
