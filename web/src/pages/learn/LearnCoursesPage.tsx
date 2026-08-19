import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  ArrowDownUp,
  Check,
  GraduationCap,
  GripVertical,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react'
import { useMemo, useState, type CSSProperties, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { coursesSectionTitle } from '@/components/layout/learnNav'
import { CourseCover, courseTypeBadgeClass } from '@/components/learn/CourseCover'
import { QueryError } from '@/components/QueryError'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { Skeleton } from '@/components/ui/Skeleton'
import { useCourseMutation, useCourses } from '@/hooks/useLearn'
import { cn } from '@/lib/cn'
import {
  CONTENT_STATUS_LABEL,
  COURSE_TYPE_LABEL,
  learnApi,
  PROGRESSION_MODE_LABEL,
  type Course,
  type CourseType,
  type ProgressionMode,
} from '@/lib/learn'
import { formatMinutes, nbsp, plural } from '@/lib/typography'

/**
 * Каталог курсов (Ф3a): видимые = mandatory по аудитории ∪
 * личные назначения. Порядок задаёт срочность, а не структура базы.
 */

type CourseState = 'overdue' | 'due' | 'active' | 'new' | 'done'

function courseState(course: Course): CourseState {
  if (course.completed) return 'done'
  if (course.due_at) {
    return new Date(course.due_at) < new Date() ? 'overdue' : 'due'
  }
  return course.lessons_completed > 0 ? 'active' : 'new'
}

const GROUPS: { label: string; states: CourseState[] }[] = [
  { label: 'Требуют внимания', states: ['overdue', 'due'] },
  { label: 'В работе', states: ['active'] },
  { label: 'Можно пройти', states: ['new'] },
  { label: 'Пройдено', states: ['done'] },
]

const FILTERS: { key: string; label: string }[] = [
  { key: 'all', label: 'Все' },
  { key: 'mandatory', label: 'Обязательные' },
  { key: 'career', label: 'Карьерные' },
  { key: 'info', label: 'Информационные' },
  { key: 'done', label: 'Пройденные' },
]

function dayWord(days: number): string {
  return plural(days, 'день', 'дня', 'дней')
}

function courseMeta(course: Course, state: CourseState): string {
  const lessons = `${course.lessons_completed} из ${course.lessons_total} уроков`
  if (state === 'overdue' && course.due_at) {
    const days = Math.max(
      1,
      Math.floor((Date.now() - new Date(course.due_at).getTime()) / 86_400_000),
    )
    return `Просрочен ${dayWord(days)} · ${lessons}`
  }
  if (state === 'due' && course.due_at) {
    const when = new Date(course.due_at).toLocaleDateString('ru-RU', {
      day: 'numeric',
      month: 'long',
    })
    return `До ${when} · ${lessons}`
  }
  if (state === 'active') return `В работе · ${lessons}`
  if (state === 'done') return 'Пройден'
  const parts = [plural(course.lessons_total, 'урок', 'урока', 'уроков')]
  if (course.estimated_minutes_total > 0) parts.push(formatMinutes(course.estimated_minutes_total))
  return parts.join(' · ')
}

/** Удаление/архив курса прямо из списка (ОС 12.08 — «не проваливаясь в курс»). */
function CourseRowActions({ course }: { course: Course }) {
  const remove = useCourseMutation(() => learnApi.deleteCourse(course.id))
  const archive = useCourseMutation(() => learnApi.setCourseStatus(course.id, 'archived'))

  if (course.published_at === null) {
    return (
      <button
        type="button"
        title="Удалить курс"
        disabled={remove.isPending}
        onClick={(e) => {
          e.preventDefault()
          if (!window.confirm(`Удалить курс «${course.title}»? Действие необратимо.`)) return
          void remove.mutateAsync(undefined as never).catch(() => undefined)
        }}
        className="rounded p-1.5 text-text2 hover:bg-surface hover:text-red"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    )
  }
  if (course.status === 'archived') return null
  return (
    <button
      type="button"
      title="В архив (публиковавшийся курс удалить нельзя)"
      disabled={archive.isPending}
      onClick={(e) => {
        e.preventDefault()
        if (!window.confirm(`Отправить курс «${course.title}» в архив?`)) return
        void archive.mutateAsync(undefined as never).catch(() => undefined)
      }}
      className="rounded p-1.5 text-text2 hover:bg-surface hover:text-text"
    >
      <Archive className="h-4 w-4" />
    </button>
  )
}

function CourseCard({
  course,
  index,
  manage,
}: {
  course: Course
  index: number
  manage?: boolean
}) {
  const navigate = useNavigate()
  const state = courseState(course)
  const pct =
    course.lessons_total > 0
      ? Math.round((course.lessons_completed / course.lessons_total) * 100)
      : 0
  const showBar = pct > 0 && state !== 'done'

  return (
    <Link
      to={`/learn/courses/${course.id}`}
      className={cn(
        'flex items-center gap-3.5 rounded-[14px] border p-2.5 text-left transition-colors',
        state === 'overdue' ? 'border-red/45 bg-red/[0.05]' : 'border-hair hover:border-amber/40',
      )}
    >
      <CourseCover
        courseType={course.course_type}
        index={index}
        muted={course.completed}
      />
      <span className="min-w-0 flex-1">
        <span className={courseTypeBadgeClass(course.course_type, course.completed)}>
          {COURSE_TYPE_LABEL[course.course_type]}
        </span>
        <span className="block text-[16px] font-semibold leading-[1.35] text-text [text-wrap:pretty] lg:text-[17px]">
          {course.title}
        </span>
        <span
          className={cn(
            'mt-[3px] block text-[13px] leading-[1.4]',
            state === 'overdue' ? 'text-text' : 'text-text2',
          )}
        >
          {nbsp(courseMeta(course, state))}
        </span>
        {showBar && (
          <span className="mt-2 flex items-center gap-2">
            <span className="block h-1 flex-1 overflow-hidden rounded-full bg-surface">
              <span
                className={cn(
                  'block h-full rounded-full',
                  state === 'overdue' ? 'bg-red' : 'bg-amber',
                )}
                style={{ width: `${pct}%` }}
              />
            </span>
            <span className="text-[11px] tabular-nums text-text2">{pct}%</span>
          </span>
        )}
      </span>
      {/* Зелёным у пройденного остаётся только медальон: заливать им карточку
          нельзя — тогда завершённое конкурирует за внимание с просроченным. */}
      {course.completed && (
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-green-deep text-bg">
          <Check className="h-3.5 w-3.5" strokeWidth={3} />
        </span>
      )}
      {manage && (
        <span className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            title="Редактировать курс"
            onClick={(e) => {
              e.preventDefault()
              navigate(`/learn/courses/${course.id}/edit`)
            }}
            className="rounded p-1.5 text-text2 hover:bg-surface hover:text-text"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <CourseRowActions course={course} />
        </span>
      )}
    </Link>
  )
}

export function LearnCoursesPage() {
  const [createOpen, setCreateOpen] = useState(false)
  const [filter, setFilter] = useState('all')

  const [orderOpen, setOrderOpen] = useState(false)

  const probe = useCourses(false)
  const canManage =
    probe.data !== undefined &&
    ['admin', 'publisher', 'author'].includes(probe.data.content_role)
  // Порядок каталога — общий для тенанта, поэтому только publisher+:
  // author правит свои курсы, но расставлять чужие ему не за что.
  const canOrder =
    probe.data !== undefined && ['admin', 'publisher'].includes(probe.data.content_role)
  const managed = useCourses(true, canManage)

  const items = useMemo(() => probe.data?.items ?? [], [probe.data])
  // Индекс обложки — от позиции курса в полном каталоге, а не в отфильтрованном.
  const indexById = useMemo(
    () => new Map(items.map((c, i) => [c.id, i])),
    [items],
  )

  const filtered = useMemo(() => {
    if (filter === 'all') return items
    if (filter === 'done') return items.filter((c) => c.completed)
    return items.filter((c) => c.course_type === filter)
  }, [items, filter])

  const groups = useMemo(
    () =>
      GROUPS.map((g) => ({
        label: g.label,
        courses: filtered.filter((c) => g.states.includes(courseState(c))),
      })).filter((g) => g.courses.length > 0),
    [filtered],
  )

  const consumerIds = new Set(items.map((c) => c.id))
  const managedOnly = (managed.data?.items ?? []).filter((c) => !consumerIds.has(c.id))

  return (
    <div className="mx-auto max-w-[680px]">
      <header className="flex items-end justify-between gap-3 px-5 pt-14">
        <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
          {coursesSectionTitle(probe.data?.content_role)}
        </h1>
        {canManage && (
          <div className="flex shrink-0 gap-2">
            {canOrder && (
              <Button variant="secondary" onClick={() => setOrderOpen(true)}>
                <ArrowDownUp className="h-4 w-4" /> Порядок
              </Button>
            )}
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" /> Курс
            </Button>
          </div>
        )}
      </header>

      {items.length > 0 && (
        <div className="flex gap-2 overflow-x-auto px-5 pb-1 pt-4">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                'h-11 shrink-0 rounded-full border px-3.5 text-[13px] font-medium transition-colors',
                filter === f.key
                  ? 'border-amber bg-amber text-on-amber'
                  : 'border-hair text-text2 hover:text-text',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-2 px-5 pb-8 pt-3">
        {probe.isLoading &&
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[84px] w-full" />)}
        {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}

        {probe.data && items.length === 0 && (
          <div className="flex flex-col items-center gap-3.5 px-7 py-16 text-center">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface text-text2">
              <GraduationCap className="h-[26px] w-[26px]" strokeWidth={1.7} />
            </span>
            <h2 className="font-display text-[19px] font-bold leading-[1.25] text-text lg:text-[22px]">
              Здесь пока пусто
            </h2>
            <p className="text-[15px] leading-[1.6] text-text2 [text-wrap:pretty]">
              Вам пока не назначено ни одного курса. Загляните на витрину — там новинки
              и то, что требует ознакомления.
            </p>
            <Link
              to="/learn"
              className="inline-flex h-12 items-center justify-center rounded-xl bg-amber px-[22px] text-[15px] font-semibold text-on-amber"
            >
              На витрину
            </Link>
          </div>
        )}

        {probe.data && items.length > 0 && filtered.length === 0 && (
          <div className="flex flex-col items-center gap-3.5 px-7 py-16 text-center">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface text-text2">
              <GraduationCap className="h-[26px] w-[26px]" strokeWidth={1.7} />
            </span>
            <h2 className="font-display text-[19px] font-bold leading-[1.25] text-text lg:text-[22px]">
              Здесь пока пусто
            </h2>
            <p className="text-[15px] leading-[1.6] text-text2 [text-wrap:pretty]">
              С этим фильтром курсов нет. Снимите фильтр или загляните на витрину.
            </p>
            <button
              type="button"
              onClick={() => setFilter('all')}
              className="inline-flex h-12 items-center justify-center rounded-xl bg-amber px-[22px] text-[15px] font-semibold text-on-amber"
            >
              Показать все курсы
            </button>
          </div>
        )}

        {groups.map((group) => (
          <div key={group.label} className="flex flex-col gap-2">
            <p className="mb-0.5 mt-4 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.09em] text-text2">
              <span>{group.label}</span>
              <span className="font-display tabular-nums">{group.courses.length}</span>
            </p>
            {group.courses.map((c) => (
              <CourseCard
                key={c.id}
                course={c}
                index={indexById.get(c.id) ?? 0}
                manage={canManage}
              />
            ))}
          </div>
        ))}

        {canManage && managedOnly.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="mb-0.5 mt-4 text-xs font-bold uppercase tracking-[0.09em] text-text2">
              Управление контентом
            </p>
            {managedOnly.map((c) => (
              <Link
                key={c.id}
                to={`/learn/courses/${c.id}/edit`}
                className="flex min-h-[44px] items-center gap-2 rounded-xl border border-hair px-3.5 py-2.5 text-[15px] text-text transition-colors hover:border-amber/40"
              >
                <span className="min-w-0 flex-1 truncate">{c.title}</span>
                <Badge variant="secondary">{CONTENT_STATUS_LABEL[c.status]}</Badge>
                <Pencil className="h-4 w-4 shrink-0 text-text2" />
                <CourseRowActions course={c} />
              </Link>
            ))}
          </div>
        )}

        {createOpen && <CreateCourseDialog onClose={() => setCreateOpen(false)} />}
        {orderOpen && (
          <CourseOrderDialog
            courses={managed.data?.items ?? items}
            onClose={() => setOrderOpen(false)}
          />
        )}
      </div>
    </div>
  )
}

// ─── Порядок каталога ────────────────────────────────────────────────────────

/**
 * ОС 19.08 «курсы нельзя расставить в нужном порядке».
 *
 * Отдельный диалог, а не dnd прямо в каталоге: список сотрудника сгруппирован
 * по срочности («Требуют внимания», «В работе»…), и перетаскивание внутри
 * такой группировки означало бы не то, что видит управляющий. Порядок общий
 * для тенанта — меняется сразу всем.
 */
function CourseOrderDialog({
  courses,
  onClose,
}: {
  courses: Course[]
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [order, setOrder] = useState<string[]>(() => courses.map((c) => c.id))
  const byId = useMemo(() => new Map(courses.map((c) => [c.id, c])), [courses])
  const rows = order.map((id) => byId.get(id)).filter(Boolean) as Course[]

  const reorder = useCourseMutation((ids: string[]) => learnApi.reorderCourses(ids))
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return
    const oldIdx = order.indexOf(String(e.active.id))
    const newIdx = order.indexOf(String(e.over.id))
    if (oldIdx === -1 || newIdx === -1) return
    setOrder(arrayMove(order, oldIdx, newIdx))
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Порядок курсов</DialogTitle>
        </DialogHeader>
        <p className="text-[13px] leading-[1.45] text-text2">
          Порядок общий для всей сети — его увидят все сотрудники. Внутри
          каталога курсы всё равно группируются по срочности, поэтому порядок
          решает внутри группы и на витрине.
        </p>
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
          <SortableContext items={order} strategy={verticalListSortingStrategy}>
            <div className="space-y-1.5">
              {rows.map((course, i) => (
                <SortableCourseRow key={course.id} course={course} index={i} />
              ))}
            </div>
          </SortableContext>
        </DndContext>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose} disabled={reorder.isPending}>
            Отмена
          </Button>
          <Button
            disabled={reorder.isPending}
            onClick={() =>
              void reorder.mutateAsync(order).then(() => {
                void qc.invalidateQueries({ queryKey: ['learn-courses'] })
                void qc.invalidateQueries({ queryKey: ['learn-home-feed'] })
                onClose()
              })
            }
          >
            Сохранить порядок
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SortableCourseRow({ course, index }: { course: Course; index: number }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: course.id })
  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }
  return (
    <div
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-2 rounded-lg border border-glass-border bg-surface px-2 py-1.5"
    >
      <button
        type="button"
        {...attributes}
        {...listeners}
        className="cursor-grab touch-none p-1 text-text3 hover:text-text"
        aria-label="Перетащить"
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <span className="w-6 shrink-0 text-center text-xs tabular-nums text-text3">
        {index + 1}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-text">{course.title}</span>
      <Badge variant="secondary">{CONTENT_STATUS_LABEL[course.status]}</Badge>
    </div>
  )
}

function CreateCourseDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [courseType, setCourseType] = useState<CourseType>('info')
  const [mode, setMode] = useState<ProgressionMode>('sequential')

  const create = useCourseMutation(() =>
    learnApi.createCourse({
      title: title.trim(),
      course_type: courseType,
      progression_mode: mode,
    }),
  )

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    void create
      .mutateAsync(undefined as never)
      .then((c) => navigate(`/learn/courses/${c.id}/edit`))
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Новый курс</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 py-3">
            <div>
              <Label htmlFor="new-course-title">Название</Label>
              <Input
                id="new-course-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={255}
                autoFocus
              />
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <div>
                <Label htmlFor="new-course-type">Тип</Label>
                <Select
                  id="new-course-type"
                  value={courseType}
                  onChange={(e) => setCourseType(e.target.value as CourseType)}
                >
                  {(Object.keys(COURSE_TYPE_LABEL) as CourseType[]).map((t) => (
                    <option key={t} value={t}>
                      {COURSE_TYPE_LABEL[t]}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="new-course-mode">Порядок уроков</Label>
                <Select
                  id="new-course-mode"
                  value={mode}
                  onChange={(e) => setMode(e.target.value as ProgressionMode)}
                >
                  {(Object.keys(PROGRESSION_MODE_LABEL) as ProgressionMode[]).map((m) => (
                    <option key={m} value={m}>
                      {PROGRESSION_MODE_LABEL[m]}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={!title.trim() || create.isPending}>
              Создать
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
