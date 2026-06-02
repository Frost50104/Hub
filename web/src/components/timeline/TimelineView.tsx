import {
  DndContext,
  PointerSensor,
  TouchSensor,
  useDraggable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState, type CSSProperties } from 'react'
import { toast } from 'sonner'

import { useTimeline } from '@/hooks/useTimeline'
import { useUpdateTask } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { type Task, type TaskPriority } from '@/lib/tasks'
import { type TimelineDependency, type TimelineSection } from '@/lib/timeline'

type Scale = 'day' | 'week' | 'month'

const PX_PER_DAY: Record<Scale, number> = {
  day: 32,
  week: 12,
  month: 4,
}

const ROW_HEIGHT = 36
const HEADER_HEIGHT = 32

const PRIORITY_FILL: Record<TaskPriority, string> = {
  low: 'bg-text3/30',
  medium: 'bg-amber/40',
  high: 'bg-amber/70',
  urgent: 'bg-red/70',
}

const PRIORITY_BORDER: Record<TaskPriority, string> = {
  low: 'border-text3',
  medium: 'border-amber/60',
  high: 'border-amber',
  urgent: 'border-red',
}

const MS_PER_DAY = 24 * 60 * 60 * 1000

interface TimelineViewProps {
  projectId: string
  onTaskClick: (taskId: string) => void
}

function startOfDay(d: Date): Date {
  const c = new Date(d)
  c.setHours(0, 0, 0, 0)
  return c
}

function diffDays(a: Date, b: Date): number {
  return Math.round((startOfDay(a).getTime() - startOfDay(b).getTime()) / MS_PER_DAY)
}

function isoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function addDays(d: Date, days: number): Date {
  const c = new Date(d)
  c.setDate(c.getDate() + days)
  return c
}

interface BarLayout {
  taskId: string
  rowIdx: number
  leftPx: number
  widthPx: number
}

export function TimelineView({ projectId, onTaskClick }: TimelineViewProps) {
  const today = useMemo(() => startOfDay(new Date()), [])
  const [scale, setScale] = useState<Scale>('day')
  // viewStart is the first day shown in the grid (≈ today - 7 by default).
  const [viewStart, setViewStart] = useState<Date>(() => addDays(today, -7))

  const pxPerDay = PX_PER_DAY[scale]
  // ~3 months for `day` scale, longer otherwise.
  const visibleDays = scale === 'day' ? 90 : scale === 'week' ? 180 : 365
  const viewEnd = addDays(viewStart, visibleDays)

  const fromIso = isoDate(viewStart)
  const toIso = isoDate(viewEnd)

  const tl = useTimeline(projectId, fromIso, toIso)
  const update = useUpdateTask(projectId)

  // Group tasks by section (preserve section order, "Без секции" first).
  const layout = useMemo(() => {
    const tasks = tl.data?.tasks ?? []
    const sections = tl.data?.sections ?? []
    const bySection = new Map<string | null, Task[]>()
    for (const t of tasks) {
      const key = t.section_id
      const bucket = bySection.get(key) ?? []
      bucket.push(t)
      bySection.set(key, bucket)
    }
    const grouped: { section: TimelineSection | null; tasks: Task[] }[] = []
    if (bySection.has(null)) {
      grouped.push({ section: null, tasks: bySection.get(null)! })
    }
    for (const s of sections) {
      if (bySection.has(s.id)) {
        grouped.push({ section: s, tasks: bySection.get(s.id)! })
      }
    }
    return grouped
  }, [tl.data])

  // Flat list of bars with computed pixel positions + row indices.
  const { bars, taskById, sectionRowAnchors, totalRows } = useMemo(() => {
    const bars: BarLayout[] = []
    const taskById = new Map<string, { task: Task; rowIdx: number }>()
    const sectionRowAnchors: { rowIdx: number; name: string }[] = []
    let rowCursor = 0
    for (const group of layout) {
      sectionRowAnchors.push({
        rowIdx: rowCursor,
        name: group.section ? group.section.name : 'Без секции',
      })
      rowCursor += 1 // section header row
      for (const t of group.tasks) {
        if (!t.due_at) {
          rowCursor += 1
          continue
        }
        const dueDay = startOfDay(new Date(t.due_at))
        const startDay = t.start_at
          ? startOfDay(new Date(t.start_at))
          : dueDay
        const leftDays = Math.max(0, diffDays(startDay, viewStart))
        const spanDays = Math.max(1, diffDays(dueDay, startDay) + 1)
        const leftPx = leftDays * pxPerDay
        const widthPx = spanDays * pxPerDay
        bars.push({ taskId: t.id, rowIdx: rowCursor, leftPx, widthPx })
        taskById.set(t.id, { task: t, rowIdx: rowCursor })
        rowCursor += 1
      }
    }
    return { bars, taskById, sectionRowAnchors, totalRows: rowCursor }
  }, [layout, pxPerDay, viewStart])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 200, tolerance: 5 },
    }),
  )

  const onDragEnd = (e: DragEndEvent) => {
    const taskId = String(e.active.id)
    const entry = taskById.get(taskId)
    if (!entry || !entry.task.due_at) return
    // Convert delta-x to whole days at current scale.
    const deltaDays = Math.round((e.delta.x ?? 0) / pxPerDay)
    if (deltaDays === 0) return
    const oldDue = new Date(entry.task.due_at)
    const newDue = addDays(oldDue, deltaDays)
    const patch: { id: string; due_at: string; start_at?: string } = {
      id: taskId,
      due_at: newDue.toISOString(),
    }
    if (entry.task.start_at) {
      const oldStart = new Date(entry.task.start_at)
      const newStart = addDays(oldStart, deltaDays)
      patch.start_at = newStart.toISOString()
    }
    update.mutate(patch, {
      onError: (err) =>
        toast.error('Не удалось перенести', {
          description: (err as Error).message,
        }),
    })
  }

  // Date header ticks. For day-scale — every day. For week — Mondays. For month — 1st.
  const headerTicks = useMemo(() => {
    const ticks: { left: number; label: string; isStrong: boolean }[] = []
    for (let i = 0; i < visibleDays; i++) {
      const d = addDays(viewStart, i)
      const isMonth1 = d.getDate() === 1
      const isMonday = d.getDay() === 1
      const showDayLabel = scale === 'day'
      const showWeekLabel = scale === 'week' && isMonday
      const showMonthLabel = scale === 'month' && isMonth1
      if (showDayLabel || showWeekLabel || showMonthLabel) {
        ticks.push({
          left: i * pxPerDay,
          label:
            scale === 'month'
              ? d.toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' })
              : d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }),
          isStrong: isMonth1,
        })
      }
    }
    return ticks
  }, [viewStart, visibleDays, pxPerDay, scale])

  const totalWidth = visibleDays * pxPerDay
  const totalHeight = HEADER_HEIGHT + totalRows * ROW_HEIGHT

  const todayOffsetPx = (() => {
    const d = diffDays(today, viewStart)
    if (d < 0 || d > visibleDays) return null
    return d * pxPerDay
  })()

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="space-y-3">
        <header className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() =>
                setViewStart(addDays(viewStart, -Math.floor(visibleDays / 4)))
              }
              className="inline-flex h-9 w-9 items-center justify-center rounded text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              aria-label="Назад"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setViewStart(addDays(today, -7))}
              className="rounded border border-glass-border bg-glass px-2.5 py-1 text-xs font-medium text-text hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            >
              Сегодня
            </button>
            <button
              type="button"
              onClick={() =>
                setViewStart(addDays(viewStart, Math.floor(visibleDays / 4)))
              }
              className="inline-flex h-9 w-9 items-center justify-center rounded text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              aria-label="Вперёд"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          <div className="flex items-center gap-1 rounded-md border border-glass-border bg-glass p-0.5">
            {(['day', 'week', 'month'] as Scale[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setScale(s)}
                className={cn(
                  'rounded px-2 py-0.5 text-[11px] font-medium uppercase tracking-wider focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
                  scale === s ? 'bg-surface text-text' : 'text-text3 hover:text-text',
                )}
              >
                {s === 'day' ? 'день' : s === 'week' ? 'нед' : 'мес'}
              </button>
            ))}
          </div>
          <div className="text-xs text-text3">
            {tl.isLoading && 'Загружаем…'}
            {tl.isError && 'Ошибка'}
          </div>
        </header>

        <div className="overflow-auto rounded-md border border-glass-border">
          <div
            className="relative bg-bg-alt"
            style={{ width: totalWidth, height: totalHeight }}
          >
            {/* Date header */}
            <div
              className="sticky top-0 z-10 border-b border-glass-border bg-bg-alt"
              style={{ height: HEADER_HEIGHT }}
            >
              {headerTicks.map((t) => (
                <div
                  key={t.left}
                  className="absolute top-0 flex h-full items-center border-l border-glass-border px-1 text-[10px] text-text3"
                  style={{ left: t.left }}
                >
                  <span className={t.isStrong ? 'font-semibold text-text2' : ''}>
                    {t.label}
                  </span>
                </div>
              ))}
            </div>

            {/* Today vertical line */}
            {todayOffsetPx !== null && (
              <div
                className="pointer-events-none absolute z-0 w-px bg-amber/70"
                style={{
                  left: todayOffsetPx,
                  top: HEADER_HEIGHT,
                  height: totalHeight - HEADER_HEIGHT,
                }}
              />
            )}

            {/* Row backgrounds + section labels */}
            {sectionRowAnchors.map((a) => (
              <div
                key={`sec-${a.rowIdx}`}
                className="absolute left-0 flex items-center border-b border-glass-border bg-surface/50 px-2 text-[11px] font-semibold uppercase tracking-wider text-text2"
                style={{
                  top: HEADER_HEIGHT + a.rowIdx * ROW_HEIGHT,
                  height: ROW_HEIGHT,
                  width: totalWidth,
                }}
              >
                {a.name}
              </div>
            ))}

            {/* Bars */}
            {bars.map((b) => {
              const t = taskById.get(b.taskId)!.task
              return (
                <DraggableBar
                  key={b.taskId}
                  task={t}
                  bar={b}
                  onClick={() => onTaskClick(b.taskId)}
                />
              )
            })}

            {/* Dependency arrows */}
            <DependencyArrows
              dependencies={tl.data?.dependencies ?? []}
              bars={bars}
            />
          </div>
        </div>
      </div>
    </DndContext>
  )
}

interface DraggableBarProps {
  task: Task
  bar: BarLayout
  onClick: () => void
}

function DraggableBar({ task, bar, onClick }: DraggableBarProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({ id: task.id })
  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    left: bar.leftPx,
    top: HEADER_HEIGHT + bar.rowIdx * ROW_HEIGHT + 6,
    width: bar.widthPx,
    height: ROW_HEIGHT - 12,
    opacity: isDragging ? 0.6 : 1,
  }
  return (
    <button
      type="button"
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      className={cn(
        'absolute z-[1] cursor-grab rounded border px-2 text-left text-[11px] active:cursor-grabbing focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
        PRIORITY_FILL[task.priority],
        PRIORITY_BORDER[task.priority],
        task.status === 'done' && 'opacity-60 line-through',
      )}
      title={task.title}
    >
      <span className="truncate text-text">{task.title}</span>
    </button>
  )
}

interface DependencyArrowsProps {
  dependencies: TimelineDependency[]
  bars: BarLayout[]
}

function DependencyArrows({ dependencies, bars }: DependencyArrowsProps) {
  const byId = useMemo(() => {
    const m = new Map<string, BarLayout>()
    for (const b of bars) m.set(b.taskId, b)
    return m
  }, [bars])
  // Render simple straight lines from predecessor's right edge to successor's
  // left edge. Skip if either endpoint is outside the visible range.
  const lines = dependencies
    .map((d) => {
      const pre = byId.get(d.predecessor_id)
      const suc = byId.get(d.successor_id)
      if (!pre || !suc) return null
      const x1 = pre.leftPx + pre.widthPx
      const y1 = HEADER_HEIGHT + pre.rowIdx * ROW_HEIGHT + ROW_HEIGHT / 2
      const x2 = suc.leftPx
      const y2 = HEADER_HEIGHT + suc.rowIdx * ROW_HEIGHT + ROW_HEIGHT / 2
      return { x1, y1, x2, y2, key: `${d.predecessor_id}-${d.successor_id}` }
    })
    .filter((l): l is { x1: number; y1: number; x2: number; y2: number; key: string } => l !== null)

  if (lines.length === 0) return null
  return (
    <svg
      className="pointer-events-none absolute inset-0 z-[2]"
      width="100%"
      height="100%"
    >
      <defs>
        <marker
          id="tl-arrow"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
        </marker>
      </defs>
      {lines.map((l) => (
        <line
          key={l.key}
          x1={l.x1}
          y1={l.y1}
          x2={l.x2}
          y2={l.y2}
          stroke="currentColor"
          strokeWidth={1.5}
          strokeDasharray="3 2"
          markerEnd="url(#tl-arrow)"
          className="text-text3"
        />
      ))}
    </svg>
  )
}
