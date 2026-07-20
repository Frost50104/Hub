import { Fragment } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/lib/cn'

const MENTION_TOKEN_RE = /(@[A-Za-z0-9._-]+)/g

/** Строковые дети → подсветка @mention; элементы — как есть.
 * `names` (handle → полное имя) превращает «@petr.popov.1104» в «@Петр Попов». */
function withMentions(
  children: React.ReactNode,
  names?: Record<string, string>,
): React.ReactNode {
  const arr = Array.isArray(children) ? children : [children]
  return arr.map((child, i) => {
    if (typeof child !== 'string') return <Fragment key={i}>{child}</Fragment>
    const parts = child.split(MENTION_TOKEN_RE)
    return (
      <Fragment key={i}>
        {parts.map((part, j) => {
          if (MENTION_TOKEN_RE.test(part)) {
            MENTION_TOKEN_RE.lastIndex = 0
            const handle = part.slice(1).toLowerCase()
            const display = names?.[handle] ? `@${names[handle]}` : part
            return (
              <span
                key={j}
                title={part}
                className="rounded bg-amber/20 px-1 font-medium text-amber"
              >
                {display}
              </span>
            )
          }
          return <Fragment key={j}>{part}</Fragment>
        })}
      </Fragment>
    )
  })
}

interface MarkdownProps {
  text: string
  /** Подсвечивать @mention внутри текста (комментарии). */
  highlightMentions?: boolean
  /** handle → полное имя: чип показывает имя вместо email-префикса. */
  mentionNames?: Record<string, string>
  className?: string
}

/**
 * Безопасный markdown-рендер (GFM): HTML не интерпретируется, ссылки
 * открываются в новой вкладке. Данные остаются plain-text — старые
 * описания без разметки выглядят как раньше.
 */
export function Markdown({
  text,
  highlightMentions,
  mentionNames,
  className,
}: MarkdownProps) {
  const wrap = highlightMentions
    ? (c: React.ReactNode) => withMentions(c, mentionNames)
    : (c: React.ReactNode) => c

  const components: Components = {
    p: ({ children }) => (
      <p className="mb-2 whitespace-pre-wrap break-words last:mb-0">
        {wrap(children)}
      </p>
    ),
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-amber underline underline-offset-2 hover:opacity-80"
      >
        {children}
      </a>
    ),
    ul: ({ children }) => (
      <ul className="mb-2 list-disc space-y-0.5 pl-5 last:mb-0">{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="mb-2 list-decimal space-y-0.5 pl-5 last:mb-0">{children}</ol>
    ),
    li: ({ children }) => <li>{wrap(children)}</li>,
    code: ({ children, className: codeCn }) => (
      <code
        className={cn(
          'rounded bg-glass px-1 py-0.5 font-mono text-[0.85em]',
          codeCn,
        )}
      >
        {children}
      </code>
    ),
    pre: ({ children }) => (
      <pre className="mb-2 overflow-x-auto rounded-md border border-glass-border bg-glass p-2 text-xs last:mb-0">
        {children}
      </pre>
    ),
    blockquote: ({ children }) => (
      <blockquote className="mb-2 border-l-2 border-amber/50 pl-3 text-text2 last:mb-0">
        {children}
      </blockquote>
    ),
    h1: ({ children }) => (
      <h1 className="mb-2 font-display text-base font-semibold">{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className="mb-1.5 font-display text-sm font-semibold">{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className="mb-1 text-sm font-semibold">{children}</h3>
    ),
    hr: () => <hr className="my-3 border-glass-border" />,
    table: ({ children }) => (
      <div className="mb-2 overflow-x-auto last:mb-0">
        <table className="w-full border-collapse text-xs">{children}</table>
      </div>
    ),
    th: ({ children }) => (
      <th className="border border-glass-border px-2 py-1 text-left font-semibold">
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className="border border-glass-border px-2 py-1">{children}</td>
    ),
  }

  return (
    <div className={cn('text-sm text-text', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
