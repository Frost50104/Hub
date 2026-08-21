import { SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'

import { TaskFilterBar } from '@/components/project/TaskFilterBar'
import { BottomSheet } from '@/components/ui/BottomSheet'
import { cn } from '@/lib/cn'
import { activeFilterCount, type TaskViewFilters } from '@/lib/taskFilters'

interface MobileFilterSheetProps {
  projectId: string
  value: TaskViewFilters
  onChange: (next: TaskViewFilters) => void
  showSort?: boolean
  showLabel?: boolean
  className?: string
}

/**
 * Фильтры проекта на телефоне: чип «Фильтры (N)» в шапке → шторка снизу с тем
 * же TaskFilterBar в столбик (макет «Доска · мобильный»: шапка компактная,
 * пять селектов в три ряда занимали ~550px из 844 — QA-0821 #13).
 */
export function MobileFilterSheet({
  projectId,
  value,
  onChange,
  showSort,
  showLabel = true,
  className,
}: MobileFilterSheetProps) {
  const [open, setOpen] = useState(false)
  const count = activeFilterCount(value)
  const reset = () => onChange({ sort: value.sort, order: value.order })

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={count > 0 ? `Фильтры, активных: ${count}` : 'Фильтры'}
        className={cn(
          'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-[12px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
          count > 0
            ? 'border-amber/50 bg-amber/10 text-text'
            : 'border-glass-border bg-glass text-text2 hover:text-text',
          className,
        )}
      >
        <SlidersHorizontal className="h-3.5 w-3.5" strokeWidth={2.2} />
        Фильтры{count > 0 ? ` (${count})` : ''}
      </button>

      <BottomSheet
        open={open}
        onOpenChange={setOpen}
        title="Фильтры"
        trailing={
          count > 0 ? (
            <button
              type="button"
              onClick={reset}
              className="-my-2 inline-flex min-h-11 items-center text-[14px] font-semibold text-text2 hover:text-text"
            >
              Сбросить
            </button>
          ) : undefined
        }
      >
        <div className="px-3 pb-4 pt-1">
          <TaskFilterBar
            layout="stack"
            projectId={projectId}
            value={value}
            onChange={onChange}
            showSort={showSort}
            showLabel={showLabel}
          />
        </div>
      </BottomSheet>
    </>
  )
}
