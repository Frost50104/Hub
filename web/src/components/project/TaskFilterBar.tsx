import { ChevronDown, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

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
  stack = false,
}: {
  /** Подпись, по которой считается ширина. */
  label: string
  value: string
  onChange: (v: string) => void
  children: React.ReactNode
  ariaLabel: string
  /** Шторка фильтров на телефоне: селект во всю ширину, 44px. */
  stack?: boolean
}) {
  return (
    <span className={cn('relative inline-flex shrink-0 items-center', stack && 'w-full')}>
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        // 8px слева + 28px справа (гнездо под шеврон); `ch` в Onest немного
        // уже среднего знака кириллицы, поэтому коэффициент 1.02. Ужато с
        // 1.05ch+40px: при 1280 с сайдбаром тулбар переносил «Колонки» на
        // вторую строку (QA-0821 #5).
        style={stack ? undefined : { width: `calc(${(label.length * 1.02).toFixed(1)}ch + 36px)` }}
        className={cn(
          'cursor-pointer appearance-none whitespace-nowrap rounded-md border border-glass-border bg-glass font-body font-medium focus-visible:border-amber focus-visible:outline-none',
          stack
            ? 'h-11 w-full pl-3 pr-[34px] text-[15px] text-text'
            : 'h-8 pl-2 pr-[28px] text-[12px] text-text2',
        )}
      >
        {children}
      </select>
      <ChevronDown
        className={cn(
          'pointer-events-none absolute h-[13px] w-[13px] text-text2',
          stack ? 'right-3' : 'right-2',
        )}
        strokeWidth={2.2}
      />
    </span>
  )
}

/** true, когда контент ряда шире контейнера — тогда справа мягкий край. */
function useOverflowing<T extends HTMLElement>(enabled: boolean) {
  const ref = useRef<T>(null)
  const [overflowing, setOverflowing] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!enabled || !el || typeof ResizeObserver === 'undefined') return
    const check = () => setOverflowing(el.scrollWidth > el.clientWidth + 1)
    check()
    const ro = new ResizeObserver(check)
    ro.observe(el)
    return () => ro.disconnect()
  }, [enabled])
  return { ref, overflowing }
}

interface TaskFilterBarProps {
  projectId: string
  value: TaskViewFilters
  onChange: (next: TaskViewFilters) => void
  /** Селект сортировки показывается только там, где он имеет смысл (List). */
  showSort?: boolean
  /** Календарь не умеет фильтр по метке на бэке. */
  showLabel?: boolean
  /** Хвостовые контролы (например «Колонки») — в ОДНОЙ строке с
   * фильтрами, чтобы тулбар не разъезжался на три этажа. */
  trailing?: React.ReactNode
  /**
   * `row` — тулбар десктопа: на lg..xl одна строка со скрытым горизонтальным
   * скроллом и мягким краем, на ≥xl перенос; `stack` — столбик контролов
   * 44px во всю ширину для мобильной шторки (MobileFilterSheet).
   */
  layout?: 'row' | 'stack'
}

export function TaskFilterBar({
  projectId,
  value,
  onChange,
  showSort,
  showLabel = true,
  trailing,
  layout = 'row',
}: TaskFilterBarProps) {
  const labels = useLabels(projectId)
  const count = activeFilterCount(value)
  const set = (patch: Partial<TaskViewFilters>) => onChange({ ...value, ...patch })
  const labelName = labels.data?.find((l) => l.id === value.label)?.name
  const stack = layout === 'stack'
  const { ref, overflowing } = useOverflowing<HTMLDivElement>(!stack)

  return (
    <div
      ref={ref}
      className={cn(
        stack
          ? 'flex flex-col gap-2'
          : cn(
              // -my-1/py-1: запас под focus-ring внутри overflow-контейнера.
              '-my-1 flex flex-nowrap items-center gap-2 overflow-x-auto overflow-y-hidden py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden xl:flex-wrap xl:overflow-visible',
              overflowing &&
                '[mask-image:linear-gradient(90deg,#000_calc(100%-28px),transparent)] xl:[mask-image:none]',
            ),
      )}
    >
      <span
        className={cn(
          'inline-flex shrink-0',
          stack &&
            'w-full [&>button]:h-11 [&>button]:w-full [&>button]:text-[15px] [&>button]:text-text',
        )}
      >
        <PeoplePicker
          variant="filter"
          value={value.assignee ?? null}
          onChange={(id) => set({ assignee: id ?? undefined })}
          placeholder="Исполнитель: все"
        />
      </span>

      <FilterSelect
        stack={stack}
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
        stack={stack}
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
          stack={stack}
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
        stack={stack}
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
          stack={stack}
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
            'inline-flex shrink-0 items-center rounded-md border border-glass-border bg-glass font-medium text-text2',
            'hover:bg-surface focus-visible:border-amber focus-visible:outline-none',
            stack ? 'h-11 w-full justify-center text-[15px]' : 'h-8 px-2.5 text-[12px]',
          )}
        >
          {value.order === 'desc' ? '↓ по убыванию' : '↑ по возрастанию'}
        </button>
      )}

      {/* В шторке «Сбросить» живёт в её шапке (MobileFilterSheet). */}
      {!stack && count > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0"
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
