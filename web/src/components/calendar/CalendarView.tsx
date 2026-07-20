import {
  DndContext,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'

import { useCalendarTasks } from '@/hooks/useCalendarTasks'
import { capitalizeFirst } from '@/lib/dates'
import { useUpdateTask } from '@/hooks/useTasks'
import { toCalendarFilters, type TaskViewFilters } from '@/lib/taskFilters'
import { type Task } from '@/lib/tasks'

import { CalendarCell } from './CalendarCell'

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
function bucketByDay(
  tasks: Task[],
  cellDates: Date[],
): Map<string, Task[]> {
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

export function CalendarView({ projectId, onTaskClick, filters }: CalendarViewProps) {
  const today = useMemo(() => startOfDay(new Date()), [])
  const [viewMonth, setViewMonth] = useState<Date>(
    new Date(today.getFullYear(), today.getMonth(), 1),
  )

  const cells = useMemo(() => gridForMonth(viewMonth), [viewMonth])
  const fromIso = toIsoDate(cells[0]!)
  const toIso = toIsoDate(cells[cells.length - 1]!)

  const calendarFilters = useMemo(() => toCalendarFilters(filters ?? {}), [filters])
  const tasks = useCalendarTasks(projectId, fromIso, toIso, calendarFilters)
  const update = useUpdateTask(projectId)
  const buckets = useMemo(
    () => bucketByDay(tasks.data ?? [], cells),
    [tasks.data, cells],
  )

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 200, tolerance: 5 },
    }),
  )

  const monthLabel = capitalizeFirst(
    viewMonth.toLocaleDateString('ru-RU', {
      month: 'long',
      year: 'numeric',
    }),
  )

  const onPrev = () =>
    setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() - 1, 1))
  const onNext = () =>
    setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() + 1, 1))
  const onToday = () =>
    setViewMonth(new Date(today.getFullYear(), today.getMonth(), 1))

  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over) return
    const overId = String(e.over.id)
    if (!overId.startsWith('cal-')) return
    const newDayIso = overId.slice('cal-'.length) // YYYY-MM-DD
    const dragData = e.active.data.current as
      | { taskId: string; day: string }
      | undefined
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

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="space-y-3">
        <header className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onPrev}
              className="inline-flex h-9 w-9 items-center justify-center rounded text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              aria-label="Предыдущий месяц"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={onToday}
              className="rounded border border-glass-border bg-glass px-2.5 py-1 text-xs font-medium text-text hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            >
              Сегодня
            </button>
            <button
              type="button"
              onClick={onNext}
              className="inline-flex h-9 w-9 items-center justify-center rounded text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              aria-label="Следующий месяц"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          <h2 className="font-display text-base font-semibold text-text md:text-lg">
            {monthLabel}
          </h2>
          <div className="text-xs text-text3">
            {tasks.isLoading && 'Загружаем…'}
            {tasks.isError && 'Ошибка загрузки'}
          </div>
        </header>

        <div className="hidden grid-cols-7 gap-px border border-glass-border bg-glass-border md:grid">
          {WEEKDAYS.map((wd) => (
            <div
              key={wd}
              className="bg-bg-alt px-2 py-1 text-center text-[11px] font-semibold uppercase tracking-wider text-text3"
            >
              {wd}
            </div>
          ))}
        </div>

        <div className="grid grid-cols-7 gap-px overflow-hidden rounded-md border border-glass-border bg-glass-border">
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
    </DndContext>
  )
}
