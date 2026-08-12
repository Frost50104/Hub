/**
 * Клиентский санитайзер rich-контента — ЗЕРКАЛО серверного whitelist
 * (`app/services/rich_content.py`). Менять только ПАРОЙ с сервером
 * (правило в docs/TECH_DEBT.md); фикстуры юнит-тестов общие по смыслу.
 *
 * Зачем: TipTap сериализует ВСЕ атрибуты схемы включая дефолты
 * (orderedList несёт `type: null`, ячейки таблиц — `align`), а паста
 * приносит ноды/марки вне whitelist — fail-closed сервер отвечал 422
 * «лишние атрибуты» / «нода запрещена», и урок «не сохранялся» (ОС 12.08).
 * Чистим на выходе редактора: editor-state не мутируется (undo цел),
 * вычищаемое либо невидимо (null-атрибуты), либо выключено схемой (code).
 */

export interface SanitizedNode {
  type?: string
  attrs?: Record<string, unknown>
  content?: SanitizedNode[]
  marks?: { type: string; attrs?: Record<string, unknown> }[]
  text?: string
}

// Нода → разрешённые attrs (пустой набор = attrs запрещены целиком).
const NODE_ATTRS: Record<string, readonly string[]> = {
  doc: [],
  paragraph: [],
  text: [],
  hardBreak: [],
  horizontalRule: [],
  blockquote: [],
  bulletList: [],
  listItem: [],
  table: [],
  tableRow: [],
  heading: ['level'],
  orderedList: ['start'],
  tableCell: ['colspan', 'rowspan', 'colwidth'],
  tableHeader: ['colspan', 'rowspan', 'colwidth'],
  callout: ['kind'],
}

// Марка → разрешённые attrs.
const MARK_ATTRS: Record<string, readonly string[]> = {
  bold: [],
  italic: [],
  underline: [],
  strike: [],
  link: ['href'],
  textStyle: ['color', 'fontSize'],
  highlight: ['color'],
}

function cleanAttrs(
  attrs: Record<string, unknown> | undefined,
  allowed: readonly string[],
): Record<string, unknown> | undefined {
  if (!attrs) return undefined
  const out: Record<string, unknown> = {}
  for (const key of allowed) {
    const v = attrs[key]
    // null/undefined-дефолты и ''-артефакты parseHTML (span без font-size
    // даёт fontSize: '') не отправляем — сервер их не ждёт.
    if (v !== null && v !== undefined && v !== '') out[key] = v
  }
  return Object.keys(out).length > 0 ? out : undefined
}

function cleanMarks(
  marks: SanitizedNode['marks'],
): SanitizedNode['marks'] | undefined {
  if (!marks?.length) return undefined
  const out: NonNullable<SanitizedNode['marks']> = []
  for (const mark of marks) {
    const allowed = MARK_ATTRS[mark.type]
    if (allowed === undefined) continue // напр. `code` из пасты — вон
    const attrs = cleanAttrs(mark.attrs, allowed)
    out.push(attrs ? { type: mark.type, attrs } : { type: mark.type })
  }
  return out.length > 0 ? out : undefined
}

/** → массив нод: известная нода вернётся одна, неизвестная развернётся
 * в свой content (текст не теряется), пустая неизвестная — исчезнет. */
function sanitizeNode(
  node: SanitizedNode,
  extraNodeTypes: ReadonlySet<string>,
): SanitizedNode[] {
  const nodeType = node.type ?? ''
  // Доменные ноды (figure/video/checkQuestion…) — НЕТРОНУТЫМИ целиком:
  // их attrs валидирует lesson_content, а checkQuestion.attrs.correct
  // в manager-режиме обязан пережить редактирование.
  if (extraNodeTypes.has(nodeType)) return [node]

  const allowed = NODE_ATTRS[nodeType]
  if (allowed === undefined) {
    // Неизвестная нода (codeBlock из старой пасты и т.п.) — разворачиваем
    // в содержимое; текст-лист заворачивать некуда, отдаём как есть.
    const inner = (node.content ?? []).flatMap((child) =>
      sanitizeNode(child, extraNodeTypes),
    )
    if (inner.length > 0) return inner
    if (typeof node.text === 'string' && node.text.length > 0) {
      return [{ type: 'text', text: node.text }]
    }
    return []
  }

  const out: SanitizedNode = { type: nodeType }
  const attrs = cleanAttrs(node.attrs, allowed)
  if (attrs) out.attrs = attrs
  if (typeof node.text === 'string') out.text = node.text
  const marks = cleanMarks(node.marks)
  if (marks) out.marks = marks
  if (node.content?.length) {
    const content = node.content.flatMap((child) =>
      sanitizeNode(child, extraNodeTypes),
    )
    if (content.length > 0) out.content = content
  }
  return [out]
}

const EMPTY_SET: ReadonlySet<string> = new Set()

/** Санитизация doc-корня; `extraNodeTypes` — доменные ноды урока
 * (news-редактор передаёт пустой набор). */
export function sanitizeRichDoc<T extends SanitizedNode>(
  doc: T,
  extraNodeTypes: ReadonlySet<string> = EMPTY_SET,
): T {
  const [clean] = sanitizeNode(doc as SanitizedNode, extraNodeTypes)
  return (clean ?? { type: 'doc' }) as T
}
