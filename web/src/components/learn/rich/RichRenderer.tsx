import { type CSSProperties, type ReactNode } from 'react'

import { cn } from '@/lib/cn'

import { CALLOUT_META, type CalloutKind } from './calloutMeta'

/**
 * Read-only рендер TipTap-JSON БЕЗ ProseMirror — рекурсивный React-walker.
 * Прохождение контента не тянет редакторские зависимости (инвариант плана).
 *
 * Fail-closed: неизвестная нода → плашка «обновите приложение» (старый
 * precache-клиент не должен молча терять блоки).
 */

interface RichNode {
  type?: string
  text?: string
  attrs?: Record<string, unknown>
  marks?: { type: string; attrs?: Record<string, unknown> }[]
  content?: RichNode[]
}

export interface RichDoc {
  schema: number
  doc: RichNode
}

const CALLOUT_STYLE: Record<CalloutKind, string> = {
  important: 'border-amber/50 bg-amber/10',
  warning: 'border-red/50 bg-red/10',
  tip: 'border-green/50 bg-green/10',
  mistake: 'border-red/50 bg-red/5',
  example: 'border-glass-border bg-surface',
  recommendation: 'border-amber/30 bg-glass',
}

function renderText(node: RichNode, key: number): ReactNode {
  let el: ReactNode = node.text ?? ''
  for (const mark of node.marks ?? []) {
    switch (mark.type) {
      case 'bold':
        el = <strong key={key}>{el}</strong>
        break
      case 'italic':
        el = <em key={key}>{el}</em>
        break
      case 'underline':
        el = <u key={key}>{el}</u>
        break
      case 'strike':
        el = <s key={key}>{el}</s>
        break
      case 'link': {
        const href = String(mark.attrs?.href ?? '')
        el = /^(https?:\/\/|mailto:|tel:)/i.test(href) ? (
          <a
            key={key}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-amber underline underline-offset-2 hover:opacity-80"
          >
            {el}
          </a>
        ) : (
          el
        )
        break
      }
      case 'textStyle': {
        const color = mark.attrs?.color
        if (typeof color === 'string') {
          el = (
            <span key={key} style={{ color } as CSSProperties}>
              {el}
            </span>
          )
        }
        break
      }
      case 'highlight': {
        const color = mark.attrs?.color
        el = (
          <mark
            key={key}
            className="rounded px-0.5"
            style={
              typeof color === 'string'
                ? ({ backgroundColor: color } as CSSProperties)
                : { backgroundColor: 'rgb(255 178 0 / 0.35)' }
            }
          >
            {el}
          </mark>
        )
        break
      }
      default:
        break
    }
  }
  return <span key={key}>{el}</span>
}

function renderChildren(node: RichNode): ReactNode {
  return (node.content ?? []).map((child, i) => <RenderNode key={i} node={child} index={i} />)
}

function RenderNode({ node, index }: { node: RichNode; index: number }): ReactNode {
  switch (node.type) {
    case 'text':
      return renderText(node, index)
    case 'paragraph':
      return <p className="my-1.5 leading-relaxed">{renderChildren(node)}</p>
    case 'heading': {
      const level = Number(node.attrs?.level) || 2
      const cls = ['text-xl', 'text-lg', 'text-base', 'text-sm'][level - 1] ?? 'text-base'
      const Tag = (`h${Math.min(Math.max(level, 1), 4)}`) as 'h1' | 'h2' | 'h3' | 'h4'
      return <Tag className={cn('mb-1.5 mt-3 font-semibold text-text', cls)}>{renderChildren(node)}</Tag>
    }
    case 'bulletList':
      return <ul className="my-1.5 list-disc space-y-0.5 pl-5">{renderChildren(node)}</ul>
    case 'orderedList':
      return <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{renderChildren(node)}</ol>
    case 'listItem':
      return <li>{renderChildren(node)}</li>
    case 'blockquote':
      return (
        <blockquote className="my-2 border-l-2 border-amber/60 pl-3 text-text2">
          {renderChildren(node)}
        </blockquote>
      )
    case 'horizontalRule':
      return <hr className="my-3 border-glass-border" />
    case 'hardBreak':
      return <br />
    case 'callout': {
      const kind = (node.attrs?.kind as CalloutKind) ?? 'important'
      const meta = CALLOUT_META[kind] ?? CALLOUT_META.important
      return (
        <div
          className={cn(
            'my-2 rounded-lg border px-3 py-2',
            CALLOUT_STYLE[kind] ?? CALLOUT_STYLE.important,
          )}
        >
          <p className="mb-0.5 text-xs font-semibold uppercase tracking-wide text-text2">
            {meta.emoji} {meta.label}
          </p>
          {renderChildren(node)}
        </div>
      )
    }
    case 'table':
      return (
        <div className="my-2 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <tbody>{renderChildren(node)}</tbody>
          </table>
        </div>
      )
    case 'tableRow':
      return <tr>{renderChildren(node)}</tr>
    case 'tableHeader':
      return (
        <th className="border border-glass-border bg-surface px-2 py-1 text-left font-semibold">
          {renderChildren(node)}
        </th>
      )
    case 'tableCell':
      return (
        <td className="border border-glass-border px-2 py-1 align-top">
          {renderChildren(node)}
        </td>
      )
    default:
      // Fail-closed: старый клиент + новая нода → видимая плашка, не молчание.
      return (
        <div className="my-2 rounded border border-dashed border-glass-border px-3 py-2 text-xs text-text3">
          Этот блок не поддерживается вашей версией приложения — обновите страницу.
        </div>
      )
  }
}

export function RichRenderer({ value, className }: { value: RichDoc | null; className?: string }) {
  if (!value || value.schema !== 1 || !value.doc) return null
  return (
    <div className={cn('text-sm text-text', className)}>{renderChildren(value.doc)}</div>
  )
}
