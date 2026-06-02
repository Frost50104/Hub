import { type CustomFieldDefinition } from '@/lib/customFields'

interface TaskListHeaderProps {
  visibleFields: CustomFieldDefinition[]
}

/**
 * Compact column header row above a list of `TaskRow` — only renders the
 * static "Срок" + dynamic custom-field labels. The fixed leading cells
 * (status checkbox, title, assignee) are obvious enough not to need
 * labels and would clutter the layout on narrow viewports.
 */
export function TaskListHeader({ visibleFields }: TaskListHeaderProps) {
  if (visibleFields.length === 0) return null
  return (
    <div className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-3 border-b border-glass-border px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-text3">
      {/* status checkbox + title columns — no header text */}
      <span aria-hidden="true" className="invisible">·</span>
      <span aria-hidden="true" className="invisible">·</span>
      {/* fields render to the right of title; we replay the suffix columns
          so headers line up with TaskRow cells. */}
      <span aria-hidden="true" className="invisible">·</span>
      <div className="flex items-center gap-3 text-right">
        {visibleFields.map((f) => (
          <span
            key={f.id}
            className="inline-block w-24 truncate text-right"
            title={f.name}
          >
            {f.name}
          </span>
        ))}
        <span className="inline-block w-24 text-right">Срок</span>
      </div>
    </div>
  )
}
