import {
  DndContext,
  PointerSensor,
  useDraggable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { ChevronLeft, ChevronRight, GanttChart } from 'lucide-react'
import { useMemo, useState, type CSSProperties } from 'react'

import { EmptyState } from '@/components/ui/EmptyState'
import { SegmentGroup } from '@/components/ui/SegmentGroup'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useUpdateTask } from '@/hooks/useTasks'
import { useTimeline } from '@/hooks/useTimeline'
import { cn } from '@/lib/cn'
import { capitalizeFirst } from '@/lib/dates'
import { isOverdue } from '@/lib/taskDates'
import { type Task, type TaskPriority } from '@/lib/tasks'
import { type TimelineDependency, type TimelineSection } from '@/lib/timeline'
import { plural } from '@/lib/typography'

type Scale = 'day' | 'week' | 'month'

/** Ширина дня по масштабу. 34px в «дне» — из макета (число месяца моноширинным). */
const PX_PER_DAY: Record<Scale, number> = { day: 34, week: 12, month: 4 }
const VISIBLE_DAYS: Record<Scale, number> = { day: 90, week: 180, month: 365 }
const SCALE_LABEL: Record<Scale, string> = { day: 'День', week: 'Неделя', month: 'Месяц' }
const SCALE_WORD: Record<Scale, string> = { day: 'день', week: 'неделя', month: 'месяц' }

const HEADER_HEIGHT = 32
/** Колонка названий: основной таргет (клавиатура/палец); полоса — ускоритель мышью. */
const NAMES_W = { desktop: 248, mobile: 150 } as const
/** Строка 36px годится мышью; на телефоне полоса 22px вдвое ниже порога тапа,
 *  а ширину менять нельзя (она равна масштабу дня) — поэтому растёт СТРОКА. */
const ROW_H = { desktop: 36, mobile: 56 } as const
const BAR_H = { desktop: 22, mobile: 44 } as const

const PRIORITY_EDGE: Record<TaskPriority, string> = {
  urgent: 'border-l-red',
  high: 'border-l-amber',
  low: 'border-l-blue-deep',
  medium: 'border-l-transparent',
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

type Row =
  | { kind: 'section'; key: string; name: string }
  | { kind: 'task'; key: string; task: Task; leftPx: number | null; widthPx: number }

interface BarLayout {
  taskId: string
  rowIdx: number
  leftPx: number
  widthPx: number
}

/**
 * Хронология (Гант). Слева — колонка названий (sticky при горизонтальной
 * прокрутке: иначе при уходе шкалы вправо строка теряет подпись), справа —
 * шкала дней и холст с полосами и связями.
 *
 * Полоса — нейтральная (`--surface` + `--glass-border`), планка 3px приоритета,
 * **при просрочке сплошной `--red`** — как красный срок в списке и красный чип
 * на доске. Текста в полосе нет: в 34px влезало два знака, обрезка давала
 * мусор; название стоит слева. Задачи без срока приходят по `include_undated`:
 * строка есть, полосы нет, внизу честная подпись «N без срока».
 */
export function TimelineView({ projectId, onTaskClick }: TimelineViewProps) {
  const isDesktop = useIsDesktop()
  const today = useMemo(() => startOfDay(new Date()), [])
  const [scale, setScale] = useState<Scale>('day')
  // viewStart = today − 7: на 390px окно с 1-го числа показывало первые семь
  // дней, где полос нет вовсе, и Гант выглядел пустым до прокрутки.
  const [viewStart, setViewStart] = useState<Date>(() => addDays(today, -7))

  const pxPerDay = PX_PER_DAY[scale]
  const visibleDays = VISIBLE_DAYS[scale]
  const viewEnd = addDays(viewStart, visibleDays)
  const namesW = isDesktop ? NAMES_W.desktop : NAMES_W.mobile
  const rowH = isDesktop ? ROW_H.desktop : ROW_H.mobile
  const barH = isDesktop ? BAR_H.desktop : BAR_H.mobile

  const tl = useTimeline(projectId, isoDate(viewStart), isoDate(viewEnd), { includeUndated: true })
  const update = useUpdateTask(projectId)

  // Строки: секции в порядке сервера, «Без секции» первой; внутри — задачи.
  const { rows, bars, taskById, undatedCount, datedCount } = useMemo(() => {
    const tasks = tl.data?.tasks ?? []
    const sections: TimelineSection[] = tl.data?.sections ?? []
    const bySection = new Map<string | null, Task[]>()
    for (const t of tasks) {
      const list = bySection.get(t.section_id) ?? []
      list.push(t)
      bySection.set(t.section_id, list)
    }
    const groups: { section: TimelineSection | null; tasks: Task[] }[] = []
    if (bySection.has(null)) groups.push({ section: null, tasks: bySection.get(null)! })
    for (const s of sections) {
      if (bySection.has(s.id)) groups.push({ section: s, tasks: bySection.get(s.id)! })
    }
    const rows: Row[] = []
    const bars: BarLayout[] = []
    const taskById = new Map<string, Task>()
    let undatedCount = 0
    let datedCount = 0
    for (const g of groups) {
      rows.push({ kind: 'section', key: `sec-${g.section?.id ?? 'none'}`, name: g.section?.name ?? 'Без секции' })
      for (const t of g.tasks) {
        taskById.set(t.id, t)
        if (!t.due_at) {
          undatedCount += 1
          rows.push({ kind: 'task', key: t.id, task: t, leftPx: null, widthPx: 0 })
          continue
        }
        datedCount += 1
        const dueDay = startOfDay(new Date(t.due_at))
        const startDay = t.start_at ? startOfDay(new Date(t.start_at)) : dueDay
        const leftDays = diffDays(startDay, viewStart)
        const spanDays = Math.max(1, diffDays(dueDay, startDay) + 1)
        const leftPx = leftDays * pxPerDay
        const widthPx = spanDays * pxPerDay
        bars.push({ taskId: t.id, rowIdx: rows.length, leftPx, widthPx })
        rows.push({ kind: 'task', key: t.id, task: t, leftPx, widthPx })
      }
    }
    return { rows, bars, taskById, undatedCount, datedCount }
  }, [tl.data, pxPerDay, viewStart])

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  const onDragEnd = (e: DragEndEvent) => {
    const taskId = String(e.active.id)
    const task = taskById.get(taskId)
    if (!task || !task.due_at) return
    const deltaDays = Math.round((e.delta.x ?? 0) / pxPerDay)
    if (deltaDays === 0) return
    const oldDue = new Date(task.due_at)
    const patch: { id: string; due_at: string; start_at?: string } = {
      id: taskId,
      due_at: addDays(oldDue, deltaDays).toISOString(),
    }
    if (task.start_at) patch.start_at = addDays(new Date(task.start_at), deltaDays).toISOString()
    update.mutate(patch)
  }

  // Шкала: в «дне» — каждая ячейка с числом; в «неделе» — понедельники;
  // в «месяце» — первые числа.
  const ticks = useMemo(() => {
    const out: { left: number; width: number; label: string; isToday: boolean; strong: boolean }[] = []
    for (let i = 0; i < visibleDays; i++) {
      const d = addDays(viewStart, i)
      if (scale === 'day') {
        out.push({
          left: i * pxPerDay,
          width: pxPerDay,
          label: String(d.getDate()),
          isToday: diffDays(d, today) === 0,
          strong: d.getDate() === 1,
        })
      } else if (scale === 'week' && d.getDay() === 1) {
        out.push({
          left: i * pxPerDay,
          width: 7 * pxPerDay,
          label: d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }),
          isToday: false,
          strong: d.getDate() <= 7,
        })
      } else if (scale === 'month' && d.getDate() === 1) {
        const dim = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()
        out.push({
          left: i * pxPerDay,
          width: dim * pxPerDay,
          label: d.toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' }),
          isToday: false,
          strong: true,
        })
      }
    }
    return out
  }, [viewStart, visibleDays, pxPerDay, scale, today])

  const totalWidth = visibleDays * pxPerDay
  const canvasHeight = rows.length * rowH
  const todayIdx = diffDays(today, viewStart)
  const todayLeft = todayIdx >= 0 && todayIdx < visibleDays ? todayIdx * pxPerDay : null

  const monthLabel = capitalizeFirst(
    addDays(viewStart, 7).toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' }),
  )

  const status = tl.isLoading ? (
    <span className="text-text2">Загружаем…</span>
  ) : tl.isError ? (
    <span className="text-red">Ошибка загрузки</span>
  ) : null

  const nav = (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => setViewStart(addDays(viewStart, -Math.floor(visibleDays / 4)))}
        className={cn(ICON_BTN, isDesktop ? 'h-8 w-8' : 'h-11 w-11')}
        aria-label="Назад"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={() => setViewStart(addDays(today, -7))}
        className={cn(
          'inline-flex items-center rounded-lg border border-glass-border px-3 text-[14px] font-medium text-text hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
          isDesktop ? 'h-8' : 'h-11',
        )}
      >
        Сегодня
      </button>
      <button
        type="button"
        onClick={() => setViewStart(addDays(viewStart, Math.floor(visibleDays / 4)))}
        className={cn(ICON_BTN, isDesktop ? 'h-8 w-8' : 'h-11 w-11')}
        aria-label="Вперёд"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  )

  const header = isDesktop ? (
    <header className="flex flex-wrap items-center justify-between gap-3 px-1">
      <div className="flex items-center gap-4">
        {nav}
        <h2 className="font-display text-[18px] font-bold text-text">{monthLabel}</h2>
      </div>
      <div className="flex items-center gap-3">
        <div className="text-[13px]">{status}</div>
        <SegmentGroup<Scale>
          ariaLabel="Масштаб"
          size="md"
          value={scale}
          onChange={setScale}
          options={(['day', 'week', 'month'] as Scale[]).map((s) => ({ value: s, label: SCALE_LABEL[s] }))}
        />
      </div>
    </header>
  ) : (
    <header className="flex flex-col gap-2 px-4 pb-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-display text-[22px] font-bold leading-[1.2] text-text">Хронология</h2>
          <p className="mt-1 text-[14px] text-text2">
            {monthLabel} · масштаб «{SCALE_WORD[scale]}»{status && <> · {status}</>}
          </p>
        </div>
        {nav}
      </div>
    </header>
  )

  if (!tl.isLoading && !tl.isError && datedCount === 0) {
    return (
      <div className="flex flex-col gap-3">
        {header}
        <div className={cn(!isDesktop && 'px-4')}>
          <EmptyState
            layout="card"
            icon={<GanttChart className="h-[26px] w-[26px]" strokeWidth={1.6} />}
            title="Нечего разложить по времени"
            text="Задача попадает на хронологию, только когда у неё есть срок. Поставьте срок — она появится здесь."
          />
        </div>
      </div>
    )
  }

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="flex flex-col gap-3">
        {header}

        {/* Один скроллер на шкалу и холст: колонка названий внутри него
            sticky left:0 — иначе при уходе шкалы вправо строка теряет подпись. */}
        <div className={cn('overflow-x-auto border-t border-hair', !isDesktop && '-mx-0')}>
          <div className="flex" style={{ width: namesW + totalWidth }}>
            {/* Колонка названий */}
            <div
              className="sticky left-0 z-10 shrink-0 border-r border-hair bg-bg"
              style={{ width: namesW }}
            >
              <div style={{ height: HEADER_HEIGHT }} className="border-b border-hair" />
              {rows.map((r) =>
                r.kind === 'section' ? (
                  <div
                    key={r.key}
                    style={{ height: rowH }}
                    className="flex items-center truncate border-b border-hair bg-tint px-3.5 text-[12px] font-bold uppercase tracking-[0.06em] text-text2"
                  >
                    <span className="truncate">{r.name}</span>
                  </div>
                ) : (
                  <button
                    key={r.key}
                    type="button"
                    onClick={() => onTaskClick(r.task.id)}
                    title={r.task.title}
                    style={{ height: rowH }}
                    className="flex w-full items-center border-b border-hair px-3.5 text-left text-[14px] text-text hover:bg-glass focus-visible:outline-none focus-visible:bg-glass focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber"
                  >
                    <span className={cn('truncate', r.task.status === 'done' && 'text-text2 line-through')}>
                      {r.task.title}
                    </span>
                  </button>
                ),
              )}
            </div>

            {/* Шкала + холст */}
            <div className="relative shrink-0" style={{ width: totalWidth }}>
              <div
                className="relative border-b border-hair bg-bg-alt"
                style={{ height: HEADER_HEIGHT }}
              >
                {ticks.map((t) => (
                  <div
                    key={t.left}
                    className={cn(
                      'absolute top-0 flex h-full items-center justify-center overflow-hidden whitespace-nowrap border-l border-hair font-mono text-[12px]',
                      t.isToday ? 'bg-amber/[0.14] font-bold text-text' : 'text-text2',
                      t.strong && !t.isToday && 'font-semibold',
                    )}
                    style={{ left: t.left, width: t.width }}
                  >
                    {t.label}
                  </div>
                ))}
              </div>

              <div className="relative" style={{ height: canvasHeight }}>
                {/* Линия «сегодня» — полоса шириной в день через все строки:
                    вертикальный ориентир сильнее подсветки одной ячейки шкалы. */}
                {todayLeft !== null && (
                  <div
                    aria-hidden
                    className="pointer-events-none absolute inset-y-0 border-l border-amber/45 bg-amber/[0.08]"
                    style={{ left: todayLeft, width: pxPerDay }}
                  />
                )}
                {/* Фоны строк — секции на --tint, задачи с разделителем */}
                {rows.map((r) => (
                  <div
                    key={`bg-${r.key}`}
                    aria-hidden
                    style={{ height: rowH }}
                    className={cn('border-b border-hair', r.kind === 'section' && 'bg-tint')}
                  />
                ))}
                {/* Полосы */}
                {bars.map((b) => (
                  <TimelineBar
                    key={b.taskId}
                    task={taskById.get(b.taskId)!}
                    bar={b}
                    rowH={rowH}
                    barH={barH}
                    draggable={isDesktop}
                    onClick={() => onTaskClick(b.taskId)}
                  />
                ))}
                <DependencyArrows
                  dependencies={tl.data?.dependencies ?? []}
                  bars={bars}
                  rowH={rowH}
                />
              </div>
            </div>
          </div>
        </div>

        <footer className={cn('flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[13px] text-text2', !isDesktop && 'px-4')}>
          <span>Пунктирная связь читается «сначала блокирующая, потом зависимая».</span>
          {undatedCount > 0 && (
            <span>
              {plural(undatedCount, 'задача', 'задачи', 'задач')} без срока — строка есть, полосы нет.
            </span>
          )}
        </footer>
      </div>
    </DndContext>
  )
}

const ICON_BTN =
  'inline-flex items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60'

function TimelineBar({
  task,
  bar,
  rowH,
  barH,
  draggable,
  onClick,
}: {
  task: Task
  bar: BarLayout
  rowH: number
  barH: number
  draggable: boolean
  onClick: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: task.id,
    disabled: !draggable,
  })
  const overdue = isOverdue(task.due_at, task.status)
  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    left: bar.leftPx,
    top: bar.rowIdx * rowH + (rowH - barH) / 2,
    width: Math.max(bar.widthPx, 8),
    height: barH,
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
      aria-label={task.title}
      title={task.title}
      className={cn(
        'absolute z-[1] rounded-md border border-l-[3px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
        draggable ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer',
        overdue ? 'border-red bg-red' : 'border-glass-border bg-surface',
        overdue ? 'border-l-red' : PRIORITY_EDGE[task.priority],
      )}
    />
  )
}

function DependencyArrows({
  dependencies,
  bars,
  rowH,
}: {
  dependencies: TimelineDependency[]
  bars: BarLayout[]
  rowH: number
}) {
  const byId = useMemo(() => {
    const m = new Map<string, BarLayout>()
    for (const b of bars) m.set(b.taskId, b)
    return m
  }, [bars])
  // Ломаная H→V→H из правого края блокирующей в левый край зависимой.
  const paths = dependencies
    .map((d) => {
      const pre = byId.get(d.predecessor_id)
      const suc = byId.get(d.successor_id)
      if (!pre || !suc) return null
      const x1 = pre.leftPx + pre.widthPx
      const y1 = pre.rowIdx * rowH + rowH / 2
      const x2 = suc.leftPx
      const y2 = suc.rowIdx * rowH + rowH / 2
      const gap = 10
      let dPath: string
      if (x2 - x1 >= gap * 2) {
        const xm = x1 + gap
        dPath = `M ${x1} ${y1} H ${xm} V ${y2} H ${x2 - 4}`
      } else {
        // Зависимая начинается раньше конца блокирующей — обходим снизу.
        const yMid = y1 + rowH / 2
        dPath = `M ${x1} ${y1} H ${x1 + gap} V ${yMid} H ${x2 - gap} V ${y2} H ${x2 - 4}`
      }
      return { key: `${d.predecessor_id}-${d.successor_id}`, d: dPath, x2, y2 }
    })
    .filter((p): p is { key: string; d: string; x2: number; y2: number } => p !== null)

  if (paths.length === 0) return null
  return (
    <svg className="pointer-events-none absolute inset-0 z-[2] text-text2" width="100%" height="100%">
      {paths.map((p) => (
        <g key={p.key}>
          <path d={p.d} fill="none" stroke="currentColor" strokeWidth={1.5} strokeDasharray="4 3" />
          <path d={`M ${p.x2 - 6} ${p.y2 - 4} L ${p.x2} ${p.y2} L ${p.x2 - 6} ${p.y2 + 4} Z`} fill="currentColor" />
        </g>
      ))}
    </svg>
  )
}
