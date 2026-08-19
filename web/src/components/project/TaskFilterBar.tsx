import { ChevronDown, X } from 'lucide-react'

import { PeoplePicker } from '@/components/PeoplePicker'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/cn'
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

/**
 * Нативный select с геометрией тулбара: 32px, радиус 6, 12/500.
 *
 * Системный шеврон жмётся к самому краю поля, поэтому `appearance:none` и свой
 * шеврон 13px в 10px от края. Ширина считается по ВЫБРАННОЙ подписи, а не по
 * самой длинной опции — иначе «Метка: любая» растягивалась бы под самое
 * длинное имя метки и ряд фильтров уезжал на три этажа. `field-sizing:content`
 * решал бы это сам, но он есть только в Chrome, а PWA на iPhone — WebKit.
 */
function FilterSelect({
  label,
  value,
  onChange,
  children,
  ariaLabel,
}: {
  /** Подпись, по которой считается ширина. */
  label: string
  value: string
  onChange: (v: string) => void
  children: React.ReactNode
  ariaLabel: string
}) {
  return (
    <span className="relative inline-flex shrink-0 items-center">
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        // 10px слева + 30px справа (гнездо под шеврон); `ch` в Onest немного
        // уже среднего знака кириллицы, поэтому коэффициент 1.05.
        style={{ width: `calc(${(label.length * 1.05).toFixed(1)}ch + 40px)` }}
        className="h-8 cursor-pointer appearance-none whitespace-nowrap rounded-md border border-glass-border bg-glass pl-2.5 pr-[30px] font-body text-[12px] font-medium text-text2 focus-visible:border-amber focus-visible:outline-none"
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-2.5 h-[13px] w-[13px] text-text2"
        strokeWidth={2.2}
      />
    </span>
  )
}

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
  const labelName = labels.data?.find((l) => l.id === value.label)?.name

  return (
    <div className="flex flex-wrap items-center gap-2">
      <PeoplePicker
        variant="filter"
        value={value.assignee ?? null}
        onChange={(id) => set({ assignee: id ?? undefined })}
        placeholder="Исполнитель: все"
      />

      <FilterSelect
        ariaLabel="Фильтр по статусу"
        label={value.status ? STATUS_LABEL[value.status] : 'Статус: все'}
        value={value.status ?? ''}
        onChange={(v) => set({ status: (v || undefined) as TaskStatus | undefined })}
      >
        <option value="">Статус: все</option>
        {(Object.keys(STATUS_LABEL) as TaskStatus[]).map((s) => (
          <option key={s} value={s}>
            {STATUS_LABEL[s]}
          </option>
        ))}
      </FilterSelect>

      <FilterSelect
        ariaLabel="Фильтр по приоритету"
        label={value.priority ? PRIORITY_LABEL[value.priority] : 'Приоритет: любой'}
        value={value.priority ?? ''}
        onChange={(v) => set({ priority: (v || undefined) as TaskPriority | undefined })}
      >
        <option value="">Приоритет: любой</option>
        {(Object.keys(PRIORITY_LABEL) as TaskPriority[]).map((p) => (
          <option key={p} value={p}>
            {PRIORITY_LABEL[p]}
          </option>
        ))}
      </FilterSelect>

      {showLabel && (labels.data?.length ?? 0) > 0 && (
        <FilterSelect
          ariaLabel="Фильтр по метке"
          label={labelName ?? 'Метка: любая'}
          value={value.label ?? ''}
          onChange={(v) => set({ label: v || undefined })}
        >
          <option value="">Метка: любая</option>
          {labels.data?.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </FilterSelect>
      )}

      <FilterSelect
        ariaLabel="Фильтр по сроку"
        label={value.due ? DUE_LABEL[value.due] : 'Срок: любой'}
        value={value.due ?? ''}
        onChange={(v) => set({ due: (v || undefined) as DuePreset | undefined })}
      >
        <option value="">Срок: любой</option>
        {(Object.keys(DUE_LABEL) as DuePreset[]).map((d) => (
          <option key={d} value={d}>
            {DUE_LABEL[d]}
          </option>
        ))}
      </FilterSelect>

      {showSort && (
        <FilterSelect
          ariaLabel="Сортировка"
          label={SORT_LABEL[value.sort ?? 'position']}
          value={value.sort ?? 'position'}
          onChange={(v) => {
            const sort = v as TaskSortField
            set({
              sort: sort === 'position' ? undefined : sort,
              order: sort === 'position' ? undefined : (value.order ?? 'asc'),
            })
          }}
        >
          {(Object.keys(SORT_LABEL) as TaskSortField[]).map((s) => (
            <option key={s} value={s}>
              {SORT_LABEL[s]}
            </option>
          ))}
        </FilterSelect>
      )}
      {showSort && value.sort && value.sort !== 'position' && (
        <button
          type="button"
          onClick={() => set({ order: value.order === 'desc' ? 'asc' : 'desc' })}
          aria-label="Направление сортировки"
          className={cn(
            'inline-flex h-8 shrink-0 items-center rounded-md border border-glass-border bg-glass px-2.5 text-[12px] font-medium text-text2',
            'hover:bg-surface focus-visible:border-amber focus-visible:outline-none',
          )}
        >
          {value.order === 'desc' ? '↓ убыв.' : '↑ возр.'}
        </button>
      )}

      {count > 0 && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onChange({ sort: value.sort, order: value.order })}
        >
          <X className="h-3.5 w-3.5" />
          Сбросить{count > 1 ? ` (${count})` : ''}
        </Button>
      )}
      {trailing}
    </div>
  )
}
