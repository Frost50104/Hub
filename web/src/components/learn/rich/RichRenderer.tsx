import { createContext, useContext, type CSSProperties, type ReactNode } from 'react'

import { cn } from '@/lib/cn'

import { CALLOUT_META, type CalloutKind } from './calloutMeta'

/**
 * Read-only рендер TipTap-JSON БЕЗ ProseMirror — рекурсивный React-walker.
 * Прохождение контента не тянет редакторские зависимости (инвариант плана).
 *
 * Fail-closed: неизвестная нода → плашка «обновите приложение» (старый
 * precache-клиент не должен молча терять блоки).
 *
 * extraNodes: расширение доменными нодами (уроки Ф3a — video/figure/
 * checkQuestion) без импорта их рендереров сюда — LessonRenderer передаёт
 * карту `{type: render}`; неизвестные типы по-прежнему fail-closed.
 *
 * Типографика — шкала редизайна (моб./десктоп): текст 17/18 при 1.65/1.7,
 * H2 21/24, H3 18/19, H4 15. Мера строки 68-72 знака вместо прежних ~105
 * (14px в колонке 768px). Ширину колонки задаёт страница, не рендерер.
 */

export interface RichNode {
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

export type ExtraNodeRenderers = Record<
  string,
  (node: RichNode, index: number) => ReactNode
>

const ExtraNodesContext = createContext<ExtraNodeRenderers>({})

/**
 * Цвета из перенесённого контента ServiceGuru — не выбор автора, а артефакт
 * миграции: 74 span'а #e60000 и 42 span'а #0066cc. На тёмной теме (она
 * дефолтная) они дают 4,15:1 и 3,59:1 при норме 4,5:1, причём красным набраны
 * инструкции «Пищевой безопасности». Красный уводим в токен (5,3:1 в тёмной,
 * 4,6:1 в светлой), синий — в обычный текст: смысла бренда он не несёт.
 *
 * Цвета из палитры редактора (TEXT_COLORS в RichEditor) сюда не попадают —
 * авторский выбор рендерер не переписывает.
 */
const LEGACY_COLORS: Record<string, string | null> = {
  '#e60000': 'rgb(var(--red))',
  '#0066cc': null,
}

function normalizeColor(value: string): string | null {
  const key = value.trim().toLowerCase()
  if (key in LEGACY_COLORS) return LEGACY_COLORS[key] ?? null
  return value
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
        // color и fontSize живут в ОДНОЙ марке — применяем оба.
        const style: CSSProperties = {}
        if (typeof mark.attrs?.color === 'string') {
          const color = normalizeColor(mark.attrs.color)
          if (color) style.color = color
        }
        if (typeof mark.attrs?.fontSize === 'string') style.fontSize = mark.attrs.fontSize
        if (Object.keys(style).length > 0) {
          el = (
            <span key={key} style={style}>
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

/**
 * Заголовки получают id ОТ ИНДЕКСА ноды, а не от слага текста: в курсах есть
 * повторяющиеся названия разделов («Как готовим»), слаг дал бы дубли id и
 * сломал бы навигацию правого рельса.
 */
export function headingAnchorId(index: number): string {
  return `s${index}`
}

/**
 * H1/H2 — Unbounded (дисплейная), H3/H4 — Onest: глобальное правило brand.css
 * делает Unbounded'ом все h1-h4, поэтому подзаголовки явно возвращаются на
 * основную гарнитуру — в макете они набраны основным шрифтом.
 */
const HEADING_CLASS: Record<number, string> = {
  1: 'mb-3 mt-11 font-display tracking-[0.01em] [text-wrap:balance] text-[24px] leading-[1.22] lg:mt-[52px] lg:text-[28px] lg:leading-[1.2]',
  2: 'mb-3 mt-11 font-display tracking-[0.01em] [text-wrap:balance] text-[21px] leading-[1.25] lg:mt-[52px] lg:text-[24px] lg:leading-[1.22]',
  3: 'mb-2 mt-8 font-body text-[18px] font-bold leading-[1.35] lg:mb-2.5 lg:mt-9 lg:text-[19px]',
  4: 'mb-2 mt-7 font-body text-[15px] font-semibold leading-[1.4]',
}

function RenderNode({ node, index }: { node: RichNode; index: number }): ReactNode {
  const extraNodes = useContext(ExtraNodesContext)
  switch (node.type) {
    case 'text':
      return renderText(node, index)
    case 'paragraph':
      return (
        <p className="mb-5 text-[17px] leading-[1.65] [text-wrap:pretty] lg:mb-[22px] lg:text-[18px] lg:leading-[1.7]">
          {renderChildren(node)}
        </p>
      )
    case 'heading': {
      const level = Math.min(Math.max(Number(node.attrs?.level) || 2, 1), 4)
      const Tag = `h${level}` as 'h1' | 'h2' | 'h3' | 'h4'
      return (
        <Tag
          id={headingAnchorId(index)}
          className={cn('scroll-mt-24 text-text', HEADING_CLASS[level])}
        >
          {renderChildren(node)}
        </Tag>
      )
    }
    case 'bulletList':
      return (
        <ul className="mb-5 list-disc space-y-1.5 pl-6 text-[17px] leading-[1.65] lg:mb-[22px] lg:text-[18px] lg:leading-[1.7]">
          {renderChildren(node)}
        </ul>
      )
    case 'orderedList':
      return (
        <ol className="mb-5 list-decimal space-y-1.5 pl-6 text-[17px] leading-[1.65] lg:mb-[22px] lg:text-[18px] lg:leading-[1.7]">
          {renderChildren(node)}
        </ol>
      )
    case 'listItem':
      // Абзац внутри пункта не начинает новый блок — иначе маркер уезжает.
      return <li className="[&>p]:mb-0">{renderChildren(node)}</li>
    case 'blockquote':
      return (
        <blockquote className="my-7 border-l-[3px] border-amber/60 pl-4 text-text2 lg:my-8 [&>p:last-child]:mb-0">
          {renderChildren(node)}
        </blockquote>
      )
    case 'horizontalRule':
      return <hr className="my-7 border-hair lg:my-8" />
    case 'hardBreak':
      return <br />
    case 'callout': {
      const kind = (node.attrs?.kind as CalloutKind) ?? 'important'
      const meta = CALLOUT_META[kind] ?? CALLOUT_META.important
      const Icon = meta.icon
      return (
        <div
          className={cn(
            'my-7 flex gap-3 rounded-xl border border-l-[3px] px-4 py-3.5 lg:my-8',
            meta.box,
          )}
        >
          {/* Тип выноски несёт левая полоса 3px, а не иконка: амбер-глиф на
              16px даёт 1,64:1 в светлой теме — в макете иконка нейтральная. */}
          <Icon className="mt-px h-5 w-5 shrink-0 text-text2" />
          <div className="min-w-0 flex-1">
            <p className="mb-1 text-xs font-bold uppercase tracking-[0.09em] text-text2">
              {meta.label}
            </p>
            <div className="[&>p:last-child]:mb-0 [&>p]:text-[16px] [&>p]:leading-[1.6]">
              {renderChildren(node)}
            </div>
          </div>
        </div>
      )
    }
    case 'table':
      return (
        <div className="my-7 overflow-x-auto lg:my-8">
          <table className="w-full border-collapse text-[15px] leading-[1.5]">
            <tbody>{renderChildren(node)}</tbody>
          </table>
        </div>
      )
    case 'tableRow':
      return <tr>{renderChildren(node)}</tr>
    case 'tableHeader':
    case 'tableCell': {
      // colspan/rowspan/align обязаны доехать до потребителя — иначе
      // объединённые ячейки «едут» (ОС 12.08).
      const Cell = node.type === 'tableHeader' ? 'th' : 'td'
      const colSpan = Number(node.attrs?.colspan) || undefined
      const rowSpan = Number(node.attrs?.rowspan) || undefined
      const align = node.attrs?.align
      return (
        <Cell
          colSpan={colSpan === 1 ? undefined : colSpan}
          rowSpan={rowSpan === 1 ? undefined : rowSpan}
          style={
            typeof align === 'string' ? ({ textAlign: align } as CSSProperties) : undefined
          }
          className={cn(
            'border border-hair px-3 py-2 [&>p]:mb-0 [&>p]:text-[15px] [&>p]:leading-[1.5]',
            node.type === 'tableHeader'
              ? 'bg-surface text-left font-semibold'
              : 'align-top',
          )}
        >
          {renderChildren(node)}
        </Cell>
      )
    }
    default: {
      const renderExtra = node.type ? extraNodes[node.type] : undefined
      if (renderExtra) return renderExtra(node, index)
      // Fail-closed: старый клиент + новая нода → видимая плашка, не молчание.
      return (
        <div className="my-7 rounded-lg border border-dashed border-hair px-4 py-3 text-sm text-text2 lg:my-8">
          Этот блок не поддерживается вашей версией приложения — обновите страницу.
        </div>
      )
    }
  }
}

export function RichRenderer({
  value,
  className,
  extraNodes,
}: {
  value: RichDoc | null
  className?: string
  extraNodes?: ExtraNodeRenderers
}) {
  if (!value || value.schema !== 1 || !value.doc) return null
  const body = (
    <div className={cn('text-text [&>*:first-child]:mt-0 [&>*:last-child]:mb-0', className)}>
      {renderChildren(value.doc)}
    </div>
  )
  if (!extraNodes) return body
  return <ExtraNodesContext.Provider value={extraNodes}>{body}</ExtraNodesContext.Provider>
}
