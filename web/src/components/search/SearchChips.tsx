import { X } from 'lucide-react'

import { type ParsedDsl } from '@/lib/search'

interface SearchChipsProps {
  parsed: ParsedDsl
  /** Called when user clicks the ✕ on a chip — caller drops the matching
   *  `field:value` token from the raw query string. */
  onRemove: (field: keyof ParsedDsl) => void
}

const STATUS_LABEL: Record<string, string> = {
  todo: 'К выполнению',
  in_progress: 'В работе',
  in_review: 'На проверке',
  done: 'Готово',
}

const PRIORITY_LABEL: Record<string, string> = {
  low: 'низкий',
  medium: 'средний',
  high: 'высокий',
  urgent: 'срочно',
}

export function SearchChips({ parsed, onRemove }: SearchChipsProps) {
  const chips: { key: keyof ParsedDsl; label: string }[] = []

  if (parsed.assignee === 'me') {
    chips.push({ key: 'assignee', label: 'мне' })
  } else if (parsed.assignee) {
    chips.push({
      key: 'assignee',
      label: `assignee: ${parsed.assignee.slice(0, 8)}…`,
    })
  }
  if (parsed.status) {
    chips.push({
      key: 'status',
      label: `статус: ${STATUS_LABEL[parsed.status] ?? parsed.status}`,
    })
  }
  if (parsed.priority) {
    chips.push({
      key: 'priority',
      label: `приоритет: ${PRIORITY_LABEL[parsed.priority] ?? parsed.priority}`,
    })
  }
  if (parsed.due_date) {
    chips.push({
      key: 'due_date',
      label: `срок ${parsed.due_op ?? '='} ${parsed.due_date}`,
    })
  }
  if (parsed.created_date) {
    chips.push({
      key: 'created_date',
      label: `создано ${parsed.created_op ?? '='} ${parsed.created_date}`,
    })
  }

  if (chips.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((chip) => (
        <button
          type="button"
          key={chip.key}
          onClick={() => onRemove(chip.key)}
          className="inline-flex items-center gap-1 rounded-full border border-glass-border bg-glass px-2 py-0.5 text-xs text-text hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
        >
          {chip.label}
          <X className="h-3 w-3 opacity-70" />
        </button>
      ))}
    </div>
  )
}
