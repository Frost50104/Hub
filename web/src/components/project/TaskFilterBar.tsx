import { X } from 'lucide-react'

import { PeoplePicker } from '@/components/PeoplePicker'
import { Button } from '@/components/ui/Button'
import { useLabels } from '@/hooks/useLabels'
import {
  activeFilterCount,
  type DuePreset,
  type TaskViewFilters,
} from '@/lib/taskFilters'
import {
  PRIORITY_LABEL,
  STATUS_LABEL,
  type TaskPriority,
  type TaskSortField,
  type TaskStatus,
} from '@/lib/tasks'

const DUE_LABEL: Record<DuePreset, string> = {
  today: 'Сегодня',
  week: 'Ближайшая неделя',
  overdue: 'Просроченные',
}

const SORT_LABEL: Record<TaskSortField, string> = {
  position: 'Вручную',
  due_at: 'По сроку',
  priority: 'По приоритету',
  created_at: 'По дате создания',
  title: 'По названию',
}

const SELECT_CLASS =
  'h-8 rounded-md border border-glass-border bg-glass px-2 text-xs text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60'

interface TaskFilterBarProps {
  projectId: string
  value: TaskViewFilters
  onChange: (next: TaskViewFilters) => void
  /** Селект сортировки показывается только там, где он имеет смысл (List). */
  showSort?: boolean
  /** Календарь не умеет фильтр по метке на бэке. */
  showLabel?: boolean
  /** Хвостовые контролы (например «Колонки») — в ОДНОЙ wrap-строке с
   * фильтрами, чтобы тулбар не разъезжался на три этажа. */
  trailing?: React.ReactNode
}

export function TaskFilterBar({
  projectId,
  value,
  onChange,
  showSort,
  showLabel = true,
  trailing,
}: TaskFilterBarProps) {
  const labels = useLabels(projectId)
  const count = activeFilterCount(value)
  const set = (patch: Partial<TaskViewFilters>) => onChange({ ...value, ...patch })

  return (
    <div className="flex flex-wrap items-center gap-2 px-1">
      <div className="w-[200px]">
        <PeoplePicker
          value={value.assignee ?? null}
          onChange={(id) => set({ assignee: id ?? undefined })}
          placeholder="Исполнитель: все"
        />
      </div>

      <select
        value={value.status ?? ''}
        onChange={(e) =>
          set({ status: (e.target.value || undefined) as TaskStatus | undefined })
        }
        aria-label="Фильтр по статусу"
        className={SELECT_CLASS}
      >
        <option value="">Статус: все</option>
        {(Object.keys(STATUS_LABEL) as TaskStatus[]).map((s) => (
          <option key={s} value={s}>
            {STATUS_LABEL[s]}
          </option>
        ))}
      </select>

      <select
        value={value.priority ?? ''}
        onChange={(e) =>
          set({
            priority: (e.target.value || undefined) as TaskPriority | undefined,
          })
        }
        aria-label="Фильтр по приоритету"
        className={SELECT_CLASS}
      >
        <option value="">Приоритет: любой</option>
        {(Object.keys(PRIORITY_LABEL) as TaskPriority[]).map((p) => (
          <option key={p} value={p}>
            {PRIORITY_LABEL[p]}
          </option>
        ))}
      </select>

      {showLabel && (labels.data?.length ?? 0) > 0 && (
        <select
          value={value.label ?? ''}
          onChange={(e) => set({ label: e.target.value || undefined })}
          aria-label="Фильтр по метке"
          className={SELECT_CLASS}
        >
          <option value="">Метка: любая</option>
          {labels.data?.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      )}

      <select
        value={value.due ?? ''}
        onChange={(e) =>
          set({ due: (e.target.value || undefined) as DuePreset | undefined })
        }
        aria-label="Фильтр по сроку"
        className={SELECT_CLASS}
      >
        <option value="">Срок: любой</option>
        {(Object.keys(DUE_LABEL) as DuePreset[]).map((d) => (
          <option key={d} value={d}>
            {DUE_LABEL[d]}
          </option>
        ))}
      </select>

      {showSort && (
        <select
          value={value.sort ?? 'position'}
          onChange={(e) => {
            const sort = e.target.value as TaskSortField
            set({
              sort: sort === 'position' ? undefined : sort,
              order: sort === 'position' ? undefined : (value.order ?? 'asc'),
            })
          }}
          aria-label="Сортировка"
          className={SELECT_CLASS}
        >
          {(Object.keys(SORT_LABEL) as TaskSortField[]).map((s) => (
            <option key={s} value={s}>
              {SORT_LABEL[s]}
            </option>
          ))}
        </select>
      )}
      {showSort && value.sort && value.sort !== 'position' && (
        <button
          type="button"
          onClick={() => set({ order: value.order === 'desc' ? 'asc' : 'desc' })}
          aria-label="Направление сортировки"
          className="h-8 rounded-md border border-glass-border bg-glass px-2 text-xs text-text2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
        >
          {value.order === 'desc' ? '↓ убыв.' : '↑ возр.'}
        </button>
      )}

      {count > 0 && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            onChange({ sort: value.sort, order: value.order })
          }
        >
          <X className="h-3.5 w-3.5" />
          Сбросить{count > 1 ? ` (${count})` : ''}
        </Button>
      )}
      {trailing}
    </div>
  )
}
