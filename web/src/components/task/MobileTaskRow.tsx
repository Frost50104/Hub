import { CheckCircle2, Circle, ClipboardCheck, Clock } from 'lucide-react'
import { Link } from 'react-router-dom'

import { cn } from '@/lib/cn'
import { type Task, type TaskStatus } from '@/lib/tasks'

const STATUS_ICON: Record<TaskStatus, typeof Circle> = {
  todo: Circle,
  in_progress: Clock,
  in_review: ClipboardCheck,
  done: CheckCircle2,
}

const STATUS_TONE: Record<TaskStatus, string> = {
  todo: 'text-text3',
  in_progress: 'text-amber',
  in_review: 'text-amber',
  done: 'text-green',
}

interface MobileTaskRowProps {
  task: Task
  /** Secondary line under the title — usually the project name. */
  subtitle?: string
  onToggleDone?: () => void
  /** Link target; falls back to deep-link into the task's project drawer. */
  href?: string
}

/**
 * Asana-mobile-style task row. Two-line layout (title + subtitle) on the
 * left, status checkbox on the far left, due-date chip pinned right.
 * Chip is **green-tinted** because Asana's mobile uses green for both
 * Today and Tomorrow — only past dates show red.
 */
export function MobileTaskRow({
  task,
  subtitle,
  onToggleDone,
  href,
}: MobileTaskRowProps) {
  const StatusIcon = STATUS_ICON[task.status]
  const due = task.due_at ? new Date(task.due_at) : null
  const target =
    href ?? (task.project_id ? `/projects/${task.project_id}?task=${task.id}` : '#')

  return (
    <Link
      to={target}
      className="flex items-center gap-3 border-b border-glass-border/60 px-4 py-3 active:bg-glass"
    >
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          onToggleDone?.()
        }}
        className={cn(
          'flex h-10 w-10 shrink-0 items-center justify-center -ml-1.5',
          STATUS_TONE[task.status],
        )}
        aria-label="Сменить статус"
      >
        <StatusIcon className="h-6 w-6" strokeWidth={1.5} />
      </button>

      <div className="min-w-0 flex-1">
        <p
          className={cn(
            'truncate text-[15px] leading-snug text-text',
            task.status === 'done' && 'text-text3 line-through',
          )}
        >
          {task.title}
        </p>
        {subtitle && (
          <p className="truncate text-xs text-text3">{subtitle}</p>
        )}
      </div>

      {due && <DueChip due={due} done={task.status === 'done'} />}
    </Link>
  )
}

function DueChip({ due, done }: { due: Date; done: boolean }) {
  const today = startOfDay(new Date())
  const dueDay = startOfDay(due)
  const diff = Math.round(
    (dueDay.getTime() - today.getTime()) / (24 * 60 * 60 * 1000),
  )
  let label: string
  let tone: 'green' | 'red' | 'muted'
  if (diff < 0 && !done) {
    label = due.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
    tone = 'red'
  } else if (diff === 0) {
    label = 'Сегодня'
    tone = 'green'
  } else if (diff === 1) {
    label = 'Завтра'
    tone = 'green'
  } else if (diff < 7) {
    label = due.toLocaleDateString('ru-RU', { weekday: 'short' })
    tone = 'muted'
  } else {
    label = due.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
    tone = 'muted'
  }
  return (
    <span
      className={cn(
        'shrink-0 rounded-md px-2 py-1 text-xs font-medium',
        tone === 'green' && 'bg-green/15 text-green',
        tone === 'red' && 'bg-red/15 text-red',
        tone === 'muted' && 'bg-surface text-text2',
      )}
    >
      {label}
    </span>
  )
}

function startOfDay(d: Date): Date {
  const c = new Date(d)
  c.setHours(0, 0, 0, 0)
  return c
}
