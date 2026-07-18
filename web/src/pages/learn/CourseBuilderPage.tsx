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
  ArrowLeft,
  Eye,
  EyeOff,
  GripVertical,
  Pencil,
  Plus,
  Trash2,
  UserPlus,
  Users,
} from 'lucide-react'
import { useState, type CSSProperties, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AudiencePicker, type AudienceValue } from '@/components/learn/AudiencePicker'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useCourse, useCourseMutation, useEmployees } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import {
  CONTENT_STATUS_LABEL,
  COURSE_TYPE_LABEL,
  learnApi,
  PROGRESSION_MODE_LABEL,
  type ContentStatus,
  type CourseDetail,
  type CourseType,
  type LessonMeta,
  type ProgressionMode,
} from '@/lib/learn'

import { LessonEditor } from './LessonEditor'

/**
 * Конструктор курса (Ф3a, author/publisher/admin): настройки, lifecycle,
 * аудитория, назначения, уроки с dnd-порядком, встроенный редактор урока.
 * Отдельный lazy-chunk, исключён из PWA-precache (globIgnores).
 */

const STATUS_ACTIONS: Record<ContentStatus, { to: ContentStatus; label: string }[]> = {
  draft: [
    { to: 'review', label: 'На согласование' },
    { to: 'published', label: 'Опубликовать' },
  ],
  review: [
    { to: 'published', label: 'Опубликовать' },
    { to: 'draft', label: 'Вернуть в черновик' },
  ],
  published: [{ to: 'archived', label: 'В архив' }],
  archived: [
    { to: 'published', label: 'Вернуть из архива' },
    { to: 'draft', label: 'В черновик' },
  ],
}

export function CourseBuilderPage() {
  const { courseId } = useParams<{ courseId: string }>()
  const isDesktop = useIsDesktop()
  const course = useCourse(courseId)
  const data = course.data

  const [editingLesson, setEditingLesson] = useState<LessonMeta | null>(null)
  const [audienceOpen, setAudienceOpen] = useState(false)
  const [assignOpen, setAssignOpen] = useState(false)

  return (
    <div className="mx-auto max-w-3xl">
      {!isDesktop && (
        <MobilePageHeader eyebrow="Конструктор" title={data?.title ?? 'Курс'} />
      )}
      <div className="space-y-4 p-4 lg:p-8">
        <Link
          to="/learn/courses"
          className="inline-flex items-center gap-1.5 text-sm text-text3 hover:text-text"
        >
          <ArrowLeft className="h-4 w-4" /> Моё обучение
        </Link>

        {course.isLoading && <SkeletonRows rows={6} />}
        {course.isError && <QueryError onRetry={() => void course.refetch()} />}

        {data && (
          <>
            <CourseSettingsCard
              course={data}
              onAudience={() => setAudienceOpen(true)}
              onAssign={() => setAssignOpen(true)}
            />
            <LessonsCard
              course={data}
              editingLessonId={editingLesson?.id ?? null}
              onEdit={(lesson) => setEditingLesson(lesson)}
            />
            {editingLesson && (
              <LessonEditor
                key={editingLesson.id}
                lessonMeta={editingLesson}
                onClose={() => setEditingLesson(null)}
              />
            )}
            {audienceOpen && (
              <CourseAudienceDialog course={data} onClose={() => setAudienceOpen(false)} />
            )}
            {assignOpen && (
              <AssignDialog course={data} onClose={() => setAssignOpen(false)} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ─── Настройки курса ─────────────────────────────────────────────────────────

function CourseSettingsCard({
  course,
  onAudience,
  onAssign,
}: {
  course: CourseDetail
  onAudience: () => void
  onAssign: () => void
}) {
  const navigate = useNavigate()
  const [title, setTitle] = useState(course.title)
  const [description, setDescription] = useState(course.description ?? '')
  const [courseType, setCourseType] = useState<CourseType>(course.course_type)
  const [mode, setMode] = useState<ProgressionMode>(course.progression_mode)

  const save = useCourseMutation(() =>
    learnApi.updateCourse(course.id, {
      title: title.trim(),
      description: description.trim() || null,
      course_type: courseType,
      progression_mode: mode,
    }),
  )
  const setStatus = useCourseMutation((status: ContentStatus) =>
    learnApi.setCourseStatus(course.id, status),
  )
  const remove = useCourseMutation(() => learnApi.deleteCourse(course.id))

  const dirty =
    title.trim() !== course.title ||
    (description.trim() || null) !== course.description ||
    courseType !== course.course_type ||
    mode !== course.progression_mode

  return (
    <div className="space-y-3 rounded-xl border border-glass-border bg-glass p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{CONTENT_STATUS_LABEL[course.status]}</Badge>
        <Badge variant={course.course_type === 'mandatory' ? 'default' : 'outline'}>
          {COURSE_TYPE_LABEL[course.course_type]}
        </Badge>
        <span className="text-xs text-text3">
          {course.audience_id === null ? 'Виден всем сотрудникам' : 'Настроена аудитория'}
        </span>
      </div>

      <div className="space-y-2">
        <div>
          <Label htmlFor="course-title">Название</Label>
          <Input
            id="course-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={255}
          />
        </div>
        <div>
          <Label htmlFor="course-desc">Описание</Label>
          <textarea
            id="course-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            maxLength={10_000}
            className="flex w-full rounded-lg border border-glass-border bg-glass px-3 py-2 text-sm text-text transition-colors placeholder:text-text3 focus-visible:border-amber focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber"
          />
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div>
            <Label htmlFor="course-type">Тип курса</Label>
            <Select
              id="course-type"
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
            <Label htmlFor="course-mode">Порядок уроков</Label>
            <Select
              id="course-mode"
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

      <div className="flex flex-wrap items-center gap-2 border-t border-glass-border pt-3">
        {dirty && (
          <Button
            size="sm"
            disabled={!title.trim() || save.isPending}
            onClick={() =>
              void save.mutateAsync(undefined as never).then(() => toast.success('Сохранено'))
            }
          >
            Сохранить
          </Button>
        )}
        {STATUS_ACTIONS[course.status].map((action) => (
          <Button
            key={action.to}
            size="sm"
            variant={action.to === 'published' ? 'default' : 'secondary'}
            disabled={setStatus.isPending}
            onClick={() =>
              void setStatus
                .mutateAsync(action.to)
                .then(() => toast.success(CONTENT_STATUS_LABEL[action.to]))
            }
          >
            {action.label}
          </Button>
        ))}
        <Button size="sm" variant="secondary" onClick={onAudience}>
          <Users className="h-4 w-4" /> Аудитория
        </Button>
        <Button size="sm" variant="secondary" onClick={onAssign}>
          <UserPlus className="h-4 w-4" /> Назначить
        </Button>
        {course.published_at === null && (
          <Button
            size="sm"
            variant="ghost"
            className="text-red"
            disabled={remove.isPending}
            onClick={() => {
              if (!window.confirm(`Удалить курс «${course.title}»?`)) return
              void remove
                .mutateAsync(undefined as never)
                .then(() => navigate('/learn/courses'))
            }}
          >
            <Trash2 className="h-4 w-4" /> Удалить
          </Button>
        )}
      </div>
    </div>
  )
}

// ─── Уроки: список + dnd ─────────────────────────────────────────────────────

function LessonsCard({
  course,
  editingLessonId,
  onEdit,
}: {
  course: CourseDetail
  editingLessonId: string | null
  onEdit: (lesson: LessonMeta) => void
}) {
  const qc = useQueryClient()
  const [order, setOrder] = useState<string[] | null>(null)
  const [newTitle, setNewTitle] = useState('')

  const lessons = (() => {
    const base = course.lessons
    if (!order) return base
    const byId = new Map(base.map((lesson) => [lesson.id, lesson]))
    return order.map((id) => byId.get(id)).filter(Boolean) as LessonMeta[]
  })()

  const create = useCourseMutation((title: string) =>
    learnApi.createLesson(course.id, { title }),
  )
  const reorder = useCourseMutation((ids: string[]) =>
    learnApi.reorderLessons(course.id, ids),
  )

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return
    const ids = lessons.map((lesson) => lesson.id)
    const oldIdx = ids.indexOf(String(e.active.id))
    const newIdx = ids.indexOf(String(e.over.id))
    if (oldIdx === -1 || newIdx === -1) return
    const next = arrayMove(ids, oldIdx, newIdx)
    setOrder(next)
    void reorder.mutateAsync(next).then(() => {
      void qc.invalidateQueries({ queryKey: ['learn-course', course.id] })
    })
  }

  const submitNew = (e: FormEvent) => {
    e.preventDefault()
    const title = newTitle.trim()
    if (!title) return
    void create.mutateAsync(title).then((lesson) => {
      setNewTitle('')
      setOrder(null)
      onEdit(lesson)
    })
  }

  return (
    <div className="space-y-2 rounded-xl border border-glass-border bg-glass p-4">
      <p className="text-sm font-semibold text-text">Уроки</p>

      {lessons.length === 0 && (
        <p className="text-sm text-text3">Добавьте первый урок — без него курс не опубликовать.</p>
      )}

      <DndContext sensors={sensors} onDragEnd={onDragEnd}>
        <SortableContext items={lessons.map((lesson) => lesson.id)} strategy={verticalListSortingStrategy}>
          <div className="space-y-1.5">
            {lessons.map((lesson, i) => (
              <SortableLessonRow
                key={lesson.id}
                lesson={lesson}
                index={i}
                active={lesson.id === editingLessonId}
                onEdit={() => onEdit(lesson)}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>

      <form onSubmit={submitNew} className="flex items-center gap-2 pt-1">
        <Input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder="Название нового урока…"
          maxLength={255}
        />
        <Button type="submit" size="sm" disabled={!newTitle.trim() || create.isPending}>
          <Plus className="h-4 w-4" /> Урок
        </Button>
      </form>
    </div>
  )
}

function SortableLessonRow({
  lesson,
  index,
  active,
  onEdit,
}: {
  lesson: LessonMeta
  index: number
  active: boolean
  onEdit: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: lesson.id })
  const toggle = useCourseMutation(() =>
    learnApi.updateLesson(lesson.id, {
      status: lesson.status === 'published' ? 'draft' : 'published',
    }),
  )
  const remove = useCourseMutation(() => learnApi.deleteLesson(lesson.id))

  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 ${
        active ? 'border-amber/60 bg-amber/5' : 'border-glass-border bg-surface'
      }`}
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
      <span className="w-5 shrink-0 text-center text-xs text-text3">{index + 1}</span>
      <button
        type="button"
        onClick={onEdit}
        className="min-w-0 flex-1 truncate text-left text-sm text-text hover:text-amber"
      >
        {lesson.title}
      </button>
      {lesson.content_format === 'pdf' && <Badge variant="outline">PDF</Badge>}
      <Badge variant={lesson.status === 'published' ? 'default' : 'secondary'}>
        {lesson.status === 'published' ? 'опубликован' : 'черновик'}
      </Badge>
      <button
        type="button"
        title={lesson.status === 'published' ? 'Скрыть (в черновик)' : 'Опубликовать'}
        disabled={toggle.isPending}
        onClick={() => void toggle.mutateAsync(undefined as never)}
        className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text"
      >
        {lesson.status === 'published' ? (
          <Eye className="h-4 w-4" />
        ) : (
          <EyeOff className="h-4 w-4" />
        )}
      </button>
      <button
        type="button"
        title="Редактировать"
        onClick={onEdit}
        className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text"
      >
        <Pencil className="h-4 w-4" />
      </button>
      <button
        type="button"
        title="Удалить"
        disabled={remove.isPending}
        onClick={() => {
          if (!window.confirm(`Удалить урок «${lesson.title}»?`)) return
          void remove.mutateAsync(undefined as never)
        }}
        className="rounded p-1.5 text-text3 hover:bg-glass hover:text-red"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  )
}

// ─── Аудитория ───────────────────────────────────────────────────────────────

function CourseAudienceDialog({
  course,
  onClose,
}: {
  course: CourseDetail
  onClose: () => void
}) {
  const [value, setValue] = useState<AudienceValue>({
    is_all: course.audience_id === null,
    rules: [],
  })
  const save = useCourseMutation(() => learnApi.setCourseAudience(course.id, value))
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Кому виден «{course.title}»</DialogTitle>
          {course.audience_id !== null && (
            <DialogDescription>
              У курса настроена аудитория. Правила ниже ЗАМЕНЯТ текущие.
            </DialogDescription>
          )}
        </DialogHeader>
        <AudiencePicker value={value} onChange={setValue} />
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            type="button"
            disabled={save.isPending}
            onClick={() =>
              void save.mutateAsync(undefined as never).then(() => {
                toast.success('Аудитория обновлена')
                onClose()
              })
            }
          >
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Назначения ──────────────────────────────────────────────────────────────

function AssignDialog({ course, onClose }: { course: CourseDetail; onClose: () => void }) {
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [dueAt, setDueAt] = useState('')
  const employees = useEmployees({ status: 'active', q: q || undefined })

  const assign = useCourseMutation(() =>
    learnApi.assignCourse(course.id, {
      profile_ids: [...selected],
      due_at: dueAt ? new Date(dueAt).toISOString() : null,
    }),
  )

  const togglePick = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Назначить «{course.title}»</DialogTitle>
          <DialogDescription>
            Назначенный курс виден сотруднику даже вне аудитории. Уведомление
            уйдёт сразу (для опубликованного курса).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск по имени или email…"
          />
          <div className="max-h-64 space-y-1 overflow-y-auto rounded-lg border border-glass-border p-1.5">
            {(employees.data?.items ?? []).map((emp) => (
              <label
                key={emp.id}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm text-text hover:bg-glass"
              >
                <input
                  type="checkbox"
                  checked={selected.has(emp.id)}
                  onChange={() => togglePick(emp.id)}
                  className="accent-amber"
                />
                <span className="min-w-0 flex-1 truncate">{emp.full_name}</span>
                <span className="truncate text-xs text-text3">{emp.email}</span>
              </label>
            ))}
            {employees.data && employees.data.items.length === 0 && (
              <p className="px-2 py-3 text-center text-sm text-text3">Никого не нашли.</p>
            )}
          </div>
          <div>
            <Label htmlFor="assign-due">Срок (необязательно)</Label>
            <Input
              id="assign-due"
              type="datetime-local"
              value={dueAt}
              onChange={(e) => setDueAt(e.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose} disabled={assign.isPending}>
            Отмена
          </Button>
          <Button
            type="button"
            disabled={selected.size === 0 || assign.isPending}
            onClick={() =>
              void assign.mutateAsync(undefined as never).then(() => {
                toast.success(`Назначено: ${selected.size}`)
                onClose()
              })
            }
          >
            Назначить ({selected.size})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
