import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { headingAnchorId, type RichDoc } from '@/components/learn/rich/RichRenderer'
import { cn } from '@/lib/cn'

/**
 * Правый рельс десктопа: разделы урока + прогресс курса.
 *
 * Якоря берутся из индексов нод, а не из слагов текста: в курсах есть
 * повторяющиеся заголовки («Как готовим»), слаг дал бы дубли id.
 */

export interface LessonSection {
  id: string
  title: string
  level: number
}

/** Заголовки верхнего уровня документа — в порядке чтения. */
export function extractSections(content: RichDoc | null): LessonSection[] {
  if (!content?.doc?.content) return []
  const out: LessonSection[] = []
  content.doc.content.forEach((node, index) => {
    if (node.type !== 'heading') return
    const level = Math.min(Math.max(Number(node.attrs?.level) || 2, 1), 4)
    if (level > 3) return
    const title = (node.content ?? [])
      .map((child) => child.text ?? '')
      .join('')
      .trim()
    if (title) out.push({ id: headingAnchorId(index), title, level })
  })
  return out
}

function useActiveSection(sections: LessonSection[]): string | null {
  const [active, setActive] = useState<string | null>(null)

  useEffect(() => {
    if (sections.length === 0) return undefined
    const nodes = sections
      .map((s) => document.getElementById(s.id))
      .filter((n): n is HTMLElement => n !== null)
    if (nodes.length === 0) return undefined

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
        if (visible) setActive(visible.target.id)
      },
      // Верхняя треть экрана — «читаемая» зона: заголовок считается активным,
      // когда доехал до неё, а не когда только показался снизу.
      { rootMargin: '-64px 0px -66% 0px', threshold: 0 },
    )
    nodes.forEach((n) => observer.observe(n))
    return () => observer.disconnect()
  }, [sections])

  return active
}

export function LessonSections({
  sections,
  courseTitle,
  courseHref,
  lessonsCompleted,
  lessonsTotal,
  overdue,
}: {
  sections: LessonSection[]
  courseTitle: string
  courseHref: string
  lessonsCompleted: number
  lessonsTotal: number
  overdue: boolean
}) {
  const active = useActiveSection(sections)
  const pct = lessonsTotal > 0 ? Math.round((lessonsCompleted / lessonsTotal) * 100) : 0

  return (
    <nav className="sticky top-6 flex w-[220px] shrink-0 flex-col gap-3.5 self-start">
      {sections.length > 0 && (
        <>
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-text2">
            Разделы урока
          </p>
          <ul className="flex flex-col gap-0.5 border-l border-hair">
            {sections.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className={cn(
                    'block py-2 pl-3.5 text-sm leading-[1.4]',
                    s.level > 2 && 'pl-6',
                    active === s.id
                      ? '-ml-px border-l-2 border-amber font-semibold text-text'
                      : 'text-text2 hover:text-text',
                  )}
                >
                  {s.title}
                </a>
              </li>
            ))}
          </ul>
        </>
      )}

      <div
        className={cn(
          'flex flex-col gap-2 pt-3.5',
          sections.length > 0 && 'mt-1.5 border-t border-hair',
        )}
      >
        <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-text2">
          Курс
        </p>
        <Link to={courseHref} className="text-sm font-semibold text-text hover:text-amber">
          {courseTitle}
        </Link>
        <div className="flex items-center gap-2">
          <span className="block h-1 flex-1 overflow-hidden rounded-full bg-surface">
            <span
              className={cn(
                'block h-full rounded-full',
                overdue ? 'bg-red' : lessonsCompleted >= lessonsTotal ? 'bg-green' : 'bg-amber',
              )}
              style={{ width: `${pct}%` }}
            />
          </span>
          <span className="text-xs tabular-nums text-text2">
            {lessonsCompleted}/{lessonsTotal}
          </span>
        </div>
      </div>
    </nav>
  )
}
