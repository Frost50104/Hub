import { describe, expect, it } from 'vitest'

import type { RichDoc } from '@/components/learn/rich/RichRenderer'

import { collectVideoNodes, pendingVideoIds, videoIdsOf } from './lessonVideoNodes'

const A = '11111111-1111-4111-8111-111111111111'
const B = '22222222-2222-4222-8222-222222222222'

const doc: RichDoc = {
  schema: 1,
  doc: {
    type: 'doc',
    content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'x' }] },
      { type: 'video', attrs: { mediaId: A.toUpperCase(), requireFullWatch: true } },
      { type: 'callout', content: [{ type: 'video', attrs: { mediaId: B } }] },
      { type: 'video', attrs: { mediaId: A } },
      { type: 'video', attrs: { mediaId: 'not-a-uuid' } },
    ],
  },
}

describe('видео-ноды урока', () => {
  it('собирает все ноды в порядке документа, id — уникальные и в нижнем регистре', () => {
    expect(collectVideoNodes(doc).map((n) => n.mediaId)).toEqual([A, B, A])
    expect(videoIdsOf(doc)).toEqual([A, B])
    expect(videoIdsOf(null)).toEqual([])
  })

  it('неготовые — только те, о ком известно', () => {
    const statuses: Record<string, 'ready' | 'processing' | 'failed'> = { [A]: 'processing' }
    expect(
      pendingVideoIds(doc, (id) => (statuses[id] ? { status: statuses[id] } : undefined)),
    ).toEqual([A])
    expect(pendingVideoIds(doc, () => undefined)).toEqual([])
    expect(pendingVideoIds(doc, () => ({ status: 'failed' }))).toEqual([A, B])
  })
})
