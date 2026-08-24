import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
} from '@dnd-kit/core'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'

import { EmptyState } from '@/components/ui/EmptyState'
import { useCalendarTasks } from '@/hooks/useCalendarTasks'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useTasks, useUpdateTask } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { capitalizeFirst } from '@/lib/dates'
import { isOverdue } from '@/lib/taskDates'
import { toCalendarFilters, type TaskViewFilters } from '@/lib/taskFilters'
import { type Task } from '@/lib/tasks'
import { plural } from '@/lib/typography'

import { CalendarCell } from './CalendarCell'
import { CalendarTaskBar } from './CalendarTaskBar'

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const MS_PER_DAY = 24 * 60 * 60 * 1000

interface CalendarViewProps {
  projectId: string
  onTaskClick: (id: string) => void
  filters?: TaskViewFilters
}

function toIsoDate(d: Date): string {
  // Local-date ISO (NOT toISOString, which converts to UTC and shifts the
  // day for negative tz-offsets). We always render in the user's wall time.
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function startOfDay(d: Date): Date {
  const c = new Date(d)
  c.setHours(0, 0, 0, 0)
  return c
}

function diffDays(a: Date, b: Date): number {
  return Math.round((startOfDay(a).getTime() - startOfDay(b).getTime()) / MS_PER_DAY)
}

function gridForMonth(viewMonth: Date): Date[] {
  // First cell — Monday on/before the 1st of the month.
  // Last cell — Sunday on/after the last day of the month, padded to 6 rows.
  const first = new Date(viewMonth.getFullYear(), viewMonth.getMonth(), 1)
  const dow = first.getDay() // 0=Sun..6=Sat
  const mondayOffset = (dow + 6) % 7 // 0=Mon..6=Sun → days BEFORE first to reach Mon
  const start = new Date(first)
  start.setDate(first.getDate() - mondayOffset)
  const cells: Date[] = []
  for (let i = 0; i < 42; i++) {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    cells.push(d)
  }
  return cells
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

/**
 * Group calendar-window tasks by ISO day. A multi-day task is added to
 * every day from start_at..due_at (or just due_at if start_at is null).
 */
function bucketByDay(tasks: Task[], cellDates: Date[]): Map<string, Task[]> {
  const buckets = new Map<string, Task[]>()
  for (const d of cellDates) buckets.set(toIsoDate(d), [])

  for (const task of tasks) {
    if (!task.due_at) continue
    const due = startOfDay(new Date(task.due_at))
    const start = task.start_at ? startOfDay(new Date(task.start_at)) : due
    // Iterate from start..due (inclusive) but clip to visible grid.
    const cursor = new Date(start)
    while (cursor <= due) {
      const key = toIsoDate(cursor)
      const bucket = buckets.get(key)
      if (bucket) bucket.push(task)
      cursor.setDate(cursor.getDate() + 1)
    }
  }
  return buckets
}

/** Мобильный список — только по сроку: многодневная задача показывается раз. */
function bucketByDue(tasks: Task[]): Map<string, Task[]> {
  const buckets = new Map<string, Task[]>()
  for (const task of tasks) {
    if (!task.due_at) continue
    const key = toIsoDate(new Date(task.due_at))
    const list = buckets.get(key) ?? []
    list.push(task)
    buckets.set(key, list)
  }
  return buckets
}

function longDate(iso: string): string {
  return new Date(iso + 'T12:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

const ICON_BTN =
  'inline-flex items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60'

/**
 * Календарь проекта. Десктоп — сетка месяца 6×7 (gap 1px на `--glass-border`),
 * плашки по статусу / красные при просрочке, перетаскивание сдвигает и срок,
 * и старт на одно число дней. Мобильный — СПИСОК дней со сроками: на 390px
 * сетка месяца нечитаема (ячейка сжимается до 55px), а пустых дней 21 из 31,
 * и прокручивать их незачем.
 */
export function CalendarView({ projectId, onTaskClick, filters }: CalendarViewProps) {
  const isDesktop = useIsDesktop()
  const today = useMemo(() => startOfDay(new Date()), [])
  const [viewMonth, setViewMonth] = useState<Date>(
    new Date(today.getFullYear(), today.getMonth(), 1),
  )
  const [dragOverDay, setDragOverDay] = useState<string | null>(null)

  const cells = useMemo(() => gridForMonth(viewMonth), [viewMonth])
  const fromIso = toIsoDate(cells[0]!)
  const toIso = toIsoDate(cells[cells.length - 1]!)

  const calendarFilters = useMemo(() => toCalendarFilters(filters ?? {}), [filters])
  const tasks = useCalendarTasks(projectId, fromIso, toIso, calendarFilters)
  // Для пустого состояния: «срок стоит у N задач из M» — без этого пустой
  // месяц читается как сбой, а не как норма.
  const allTasks = useTasks(projectId)
  const update = useUpdateTask(projectId)
  const buckets = useMemo(() => bucketByDay(tasks.data ?? [], cells), [tasks.data, cells])
  const dueBuckets = useMemo(() => bucketByDue(tasks.data ?? []), [tasks.data])

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  // «Август 2026», без « г.» — как в макете.
  const monthLabel = capitalizeFirst(
    viewMonth.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' }).replace(/\s?г\.$/, ''),
  )
  const monthGenitive = viewMonth.toLocaleDateString('ru-RU', { month: 'long', day: 'numeric' }).replace(/^\d+\s/, '')

  const onPrev = () =>
    setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() - 1, 1))
  const onNext = () =>
    setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() + 1, 1))
  const onToday = () =>
    setViewMonth(new Date(today.getFullYear(), today.getMonth(), 1))

  const inMonth = (t: Task) => {
    if (!t.due_at) return false
    const d = new Date(t.due_at)
    return d.getMonth() === viewMonth.getMonth() && d.getFullYear() === viewMonth.getFullYear()
  }
  const monthTasks = (tasks.data ?? []).filter(inMonth)
  const overdueCount = monthTasks.filter((t) => isOverdue(t.due_at, t.done)).length

  const onDragOver = (e: DragOverEvent) => {
    const overId = e.over ? String(e.over.id) : ''
    setDragOverDay(overId.startsWith('cal-') ? overId.slice('cal-'.length) : null)
  }

  const onDragEnd = (e: DragEndEvent) => {
    setDragOverDay(null)
    if (!e.over) return
    const overId = String(e.over.id)
    if (!overId.startsWith('cal-')) return
    const newDayIso = overId.slice('cal-'.length) // YYYY-MM-DD
    const dragData = e.active.data.current as { taskId: string; day: string } | undefined
    if (!dragData) return
    if (dragData.day === newDayIso) return

    const task = (tasks.data ?? []).find((t) => t.id === dragData.taskId)
    if (!task || !task.due_at) return

    const sourceDay = new Date(dragData.day + 'T12:00:00')
    const targetDay = new Date(newDayIso + 'T12:00:00')
    const offsetDays = diffDays(targetDay, sourceDay)
    if (offsetDays === 0) return

    const oldDue = new Date(task.due_at)
    const newDue = new Date(oldDue)
    newDue.setDate(oldDue.getDate() + offsetDays)

    const patch: { id: string; due_at: string; start_at?: string } = {
      id: task.id,
      due_at: newDue.toISOString(),
    }
    if (task.start_at) {
      const oldStart = new Date(task.start_at)
      const newStart = new Date(oldStart)
      newStart.setDate(oldStart.getDate() + offsetDays)
      patch.start_at = newStart.toISOString()
    }
    update.mutate(patch)
  }

  const note = tasks.isLoading ? (
    <span className="text-text2">Загружаем…</span>
  ) : tasks.isError ? (
    <span className="text-red">Ошибка загрузки</span>
  ) : overdueCount > 0 ? (
    <span className="text-text2">{overdueCount} просрочено</span>
  ) : null

  const emptyMonth = !tasks.isLoading && !tasks.isError && monthTasks.length === 0
  const withDue = (allTasks.data ?? []).filter((t) => t.due_at).length
  const total = allTasks.data?.length ?? 0
  const emptyText =
    total > 0
      ? `Срок стоит у ${plural(withDue, 'задачи', 'задач', 'задач')} из ${total} — пустой месяц здесь норма, а не сбой.`
      : 'Задача попадает в календарь, когда у неё есть срок.'

  // ── Мобильный: список дней со сроками ────────────────────────────────────
  if (!isDesktop) {
    const days = cells
      .map((d) => toIsoDate(d))
      .filter((iso) => {
        const d = new Date(iso + 'T12:00:00')
        return d.getMonth() === viewMonth.getMonth() && (dueBuckets.get(iso)?.length ?? 0) > 0
      })
    const count = days.reduce((s, iso) => s + (dueBuckets.get(iso)?.length ?? 0), 0)
    return (
      <div className="flex flex-col">
        <header className="flex items-start justify-between gap-3 px-4 pb-2.5">
          <div className="min-w-0">
            <h2 className="font-display text-[22px] font-bold leading-[1.2] text-text">
              {monthLabel}
            </h2>
            <p className="mt-1 text-[14px] text-text2">
              {tasks.isLoading
                ? 'Загружаем…'
                : count > 0
                  ? `Дни со сроками — ${plural(count, 'задача', 'задачи', 'задач')}`
                  : 'Дней со сроками нет'}
            </p>
          </div>
          <div className="flex shrink-0 items-center">
            <button type="button" onClick={onPrev} className={cn(ICON_BTN, 'h-11 w-11')} aria-label="Предыдущий месяц">
              <ChevronLeft className="h-5 w-5" />
            </button>
            <button type="button" onClick={onNext} className={cn(ICON_BTN, 'h-11 w-11')} aria-label="Следующий месяц">
              <ChevronRight className="h-5 w-5" />
            </button>
          </div>
        </header>
        {emptyMonth ? (
          <div className="px-4 pt-2">
            <EmptyState
              layout="card"
              icon={<CalendarDays className="h-[26px] w-[26px]" strokeWidth={1.6} />}
              title={`В ${monthGenitive} нет задач со сроком`}
              text={emptyText}
            />
          </div>
        ) : (
          <ul className="flex flex-col border-t border-hair">
            {days.map((iso) => {
              const d = new Date(iso + 'T12:00:00')
              const isToday = isSameDay(d, today)
              return (
                <li key={iso} className="flex gap-3 border-b border-hair px-4 py-[11px]">
                  <span
                    className={cn(
                      'inline-flex h-[22px] min-w-[22px] shrink-0 items-center justify-center rounded-md px-1 font-mono text-[12px]',
                      isToday ? 'bg-amber font-bold text-on-amber' : 'text-text2',
                    )}
                  >
                    {d.getDate()}
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <span className="text-[12px] font-bold uppercase tracking-[0.06em] text-text2">
                      {d.toLocaleDateString('ru-RU', { weekday: 'short' })}
                    </span>
                    {(dueBuckets.get(iso) ?? []).map((task) => (
                      <CalendarTaskBar
                        key={task.id}
                        task={task}
                        day={iso}
                        variant="list"
                        onClick={() => onTaskClick(task.id)}
                      />
                    ))}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    )
  }

  // ── Десктоп: сетка месяца ────────────────────────────────────────────────
  return (
    <DndContext sensors={sensors} onDragOver={onDragOver} onDragEnd={onDragEnd}>
      <div className="flex flex-col gap-3">
        <header className="flex items-center justify-between gap-3 px-1">
          <div className="flex items-center gap-1.5">
            <button type="button" onClick={onPrev} className={cn(ICON_BTN, 'h-8 w-8')} aria-label="Предыдущий месяц">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={onToday}
              className="inline-flex h-8 items-center rounded-lg border border-glass-border px-3 text-[14px] font-medium text-text hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            >
              Сегодня
            </button>
            <button type="button" onClick={onNext} className={cn(ICON_BTN, 'h-8 w-8')} aria-label="Следующий месяц">
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          <h2 className="font-display text-[18px] font-bold text-text">{monthLabel}</h2>
          <div className="min-w-[96px] text-right text-[13px]">{note}</div>
        </header>

        {dragOverDay && (
          <p className="rounded-lg border border-dashed border-amber/50 bg-amber/[0.05] px-3.5 py-2 text-[14px] text-text">
            Перенос задачи сдвигает и срок, и дату начала на то же число дней — {longDate(dragOverDay)}
          </p>
        )}

        {emptyMonth ? (
          <EmptyState
            layout="card"
            icon={<CalendarDays className="h-[26px] w-[26px]" strokeWidth={1.6} />}
            title={`В ${monthGenitive} нет задач со сроком`}
            text={emptyText}
          />
        ) : (
          <div className="overflow-hidden rounded-[10px] border border-glass-border">
            <div className="grid grid-cols-7 gap-px bg-glass-border">
              {WEEKDAYS.map((wd) => (
                <div
                  key={wd}
                  className="bg-bg-alt px-1 py-1.5 text-center text-[12px] font-bold uppercase tracking-[0.06em] text-text2"
                >
                  {wd}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-px border-t border-glass-border bg-glass-border">
              {cells.map((d) => {
                const iso = toIsoDate(d)
                return (
                  <CalendarCell
                    key={iso}
                    day={iso}
                    dayNumber={d.getDate()}
                    isCurrentMonth={d.getMonth() === viewMonth.getMonth()}
                    isToday={isSameDay(d, today)}
                    tasks={buckets.get(iso) ?? []}
                    onTaskClick={onTaskClick}
                  />
                )
              })}
            </div>
          </div>
        )}
      </div>
    </DndContext>
  )
}
