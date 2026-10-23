import { describe, expect, it } from 'vitest'

import type { RichDoc } from '@/components/learn/rich/RichRenderer'

import {
  collectVideoNodes,
  pendingVideoIds,
  revertedVideoAttrs,
  swappedVideoAttrs,
  videoIdsOf,
} from './lessonVideoNodes'

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

describe('замена оригинала производной', () => {
  const C = '33333333-3333-4333-8333-333333333333'
  const M = '44444444-4444-4444-8444-444444444444'

  it('первая замена запоминает оригинал, вторая его не перетирает', () => {
    const base = { mediaId: A, src: '/a', requireFullWatch: true, disableSeek: false }
    const cleaned = swappedVideoAttrs(base, { mediaId: C, src: '/c', derivedKind: 'cleaned' })
    expect(cleaned).toEqual({
      mediaId: C,
      src: '/c',
      requireFullWatch: true,
      disableSeek: false,
      sourceMediaId: A,
      derivedKind: 'cleaned',
    })
    const composed = swappedVideoAttrs(cleaned, { mediaId: M, src: null, derivedKind: 'composed' })
    expect(composed.sourceMediaId).toBe(A)
    expect(composed.mediaId).toBe(M)
    expect(composed.derivedKind).toBe('composed')
  })

  it('откат возвращает оригинал и забывает производную', () => {
    const swapped = swappedVideoAttrs(
      { mediaId: A, src: '/a' },
      { mediaId: C, src: '/c', derivedKind: 'cleaned' },
    )
    expect(revertedVideoAttrs(swapped, '/a2')).toEqual({
      mediaId: A,
      src: '/a2',
      sourceMediaId: null,
      derivedKind: null,
    })
    expect(revertedVideoAttrs({ mediaId: A, src: '/a' }, '/a')).toBeNull()
  })
})
