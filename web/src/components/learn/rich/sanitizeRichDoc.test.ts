import { describe, expect, it } from 'vitest'

import { sanitizeRichDoc, type SanitizedNode } from './sanitizeRichDoc'

const LESSON_TYPES: ReadonlySet<string> = new Set([
  'figure',
  'gallery',
  'video',
  'pdfEmbed',
  'surveyEmbed',
  'checkQuestion',
])

const text = (t: string, marks?: SanitizedNode['marks']): SanitizedNode =>
  marks ? { type: 'text', text: t, marks } : { type: 'text', text: t }

describe('sanitizeRichDoc — зеркало rich_content.py (менять парой!)', () => {
  it('orderedList: TipTap 3.28 шлёт type:null — вычищаем, start остаётся', () => {
    // Реальный вывод getJSON() редактора (ОС 12.08: 422 «лишние атрибуты: ['type']»)
    const doc: SanitizedNode = {
      type: 'doc',
      content: [
        {
          type: 'orderedList',
          attrs: { start: 3, type: null },
          content: [
            { type: 'listItem', content: [{ type: 'paragraph', content: [text('раз')] }] },
          ],
        },
      ],
    }
    const clean = sanitizeRichDoc(doc)
    expect(clean.content?.[0]?.attrs).toEqual({ start: 3 })
  })

  it('tableCell/tableHeader: align вычищается, colspan/rowspan остаются', () => {
    const doc: SanitizedNode = {
      type: 'doc',
      content: [
        {
          type: 'table',
          content: [
            {
              type: 'tableRow',
              content: [
                {
                  type: 'tableHeader',
                  attrs: { colspan: 2, rowspan: 1, colwidth: null, align: null },
                  content: [{ type: 'paragraph', content: [text('шапка')] }],
                },
                {
                  type: 'tableCell',
                  attrs: { colspan: 1, rowspan: 1, colwidth: null, align: 'left' },
                  content: [{ type: 'paragraph' }],
                },
              ],
            },
          ],
        },
      ],
    }
    const row = sanitizeRichDoc(doc).content?.[0]?.content?.[0]
    expect(row?.content?.[0]?.attrs).toEqual({ colspan: 2, rowspan: 1 })
    expect(row?.content?.[1]?.attrs).toEqual({ colspan: 1, rowspan: 1 })
  })

  it('паста: нода codeBlock разворачивается в текст, марка code выпадает', () => {
    const doc: SanitizedNode = {
      type: 'doc',
      content: [
        { type: 'codeBlock', attrs: { language: null }, content: [text('const x = 1')] },
        { type: 'paragraph', content: [text('до '), text('код', [{ type: 'code' }]), text(' после')] },
      ],
    }
    const clean = sanitizeRichDoc(doc)
    // codeBlock исчез как нода, но текст выжил
    expect(JSON.stringify(clean)).toContain('const x = 1')
    expect(JSON.stringify(clean)).not.toContain('codeBlock')
    const para = clean.content?.find((n) => n.type === 'paragraph')
    expect(para?.content?.[1]?.marks).toBeUndefined()
  })

  it('marks: link оставляет только href, textStyle — color+fontSize', () => {
    const doc: SanitizedNode = {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [
            text('ссылка', [
              { type: 'link', attrs: { href: 'https://x.ru', target: '_blank', rel: 'noopener', class: null } },
            ]),
            text('цвет', [
              { type: 'textStyle', attrs: { color: '#FFB200', fontSize: '24px', fontFamily: null } },
            ]),
          ],
        },
      ],
    }
    const para = sanitizeRichDoc(doc).content?.[0]
    expect(para?.content?.[0]?.marks?.[0]).toEqual({
      type: 'link',
      attrs: { href: 'https://x.ru' },
    })
    expect(para?.content?.[1]?.marks?.[0]).toEqual({
      type: 'textStyle',
      attrs: { color: '#FFB200', fontSize: '24px' },
    })
  })

  it('паста: ""-артефакты parseHTML вычищаются (span с color даёт fontSize:"")', () => {
    // Реальный вывод getJSON() после пасты <span style="color:#ff0000"> —
    // TipTap parseHTML кладёт fontSize: '' (ОС 12.08: 422 «некорректный fontSize»)
    const doc: SanitizedNode = {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [
            text('красный', [
              { type: 'textStyle', attrs: { color: 'rgb(255, 0, 0)', fontSize: '' } },
            ]),
            text('крупный', [{ type: 'textStyle', attrs: { color: '', fontSize: '24px' } }]),
          ],
        },
      ],
    }
    const para = sanitizeRichDoc(doc).content?.[0]
    expect(para?.content?.[0]?.marks?.[0]).toEqual({
      type: 'textStyle',
      attrs: { color: 'rgb(255, 0, 0)' },
    })
    expect(para?.content?.[1]?.marks?.[0]).toEqual({
      type: 'textStyle',
      attrs: { fontSize: '24px' },
    })
  })

  it('доменные ноды урока проходят НЕТРОНУТЫМИ (checkQuestion.correct жив)', () => {
    const check: SanitizedNode = {
      type: 'checkQuestion',
      attrs: {
        blockId: 'b1',
        question: 'Сколько будет 2+2?',
        options: ['3', '4'],
        correct: 1,
        gateNext: true,
      },
    }
    const doc: SanitizedNode = { type: 'doc', content: [check] }
    const clean = sanitizeRichDoc(doc, LESSON_TYPES)
    expect(clean.content?.[0]).toEqual(check)
  })

  it('без extraNodeTypes доменная нода без текста исчезает (news-режим)', () => {
    const doc: SanitizedNode = {
      type: 'doc',
      content: [{ type: 'figure', attrs: { mediaId: 'x' } }, { type: 'paragraph' }],
    }
    const clean = sanitizeRichDoc(doc)
    expect(clean.content).toHaveLength(1)
    expect(clean.content?.[0]?.type).toBe('paragraph')
  })

  it('heading/callout attrs сохраняются', () => {
    const doc: SanitizedNode = {
      type: 'doc',
      content: [
        { type: 'heading', attrs: { level: 1 }, content: [text('H1')] },
        { type: 'callout', attrs: { kind: 'tip' }, content: [{ type: 'paragraph' }] },
      ],
    }
    const clean = sanitizeRichDoc(doc)
    expect(clean.content?.[0]?.attrs).toEqual({ level: 1 })
    expect(clean.content?.[1]?.attrs).toEqual({ kind: 'tip' })
  })
})
