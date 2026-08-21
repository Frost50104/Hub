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
  Copy,
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

import { coursesSectionTitle } from '@/components/layout/learnNav'
import { AudiencePicker, useAudienceDraft } from '@/components/learn/AudiencePicker'
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
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { Select } from '@/components/ui/Select'
import { Switch } from '@/components/ui/Switch'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useCourse, useCourseMutation, useEmployees } from '@/hooks/useLearn'
import { useMe } from '@/hooks/useMe'
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

  const me = useMe()
  const coursesTitle = coursesSectionTitle(
    me.data?.profile?.content_role,
    me.data?.hub_role,
  )

  const [editingLesson, setEditingLesson] = useState<LessonMeta | null>(null)
  const [audienceOpen, setAudienceOpen] = useState(false)
  const [assignOpen, setAssignOpen] = useState(false)
  const navigate = useNavigate()
  const setStatus = useCourseMutation((status: ContentStatus) =>
    learnApi.setCourseStatus(courseId!, status),
  )
  const duplicate = useCourseMutation(() => learnApi.duplicateCourse(courseId!))

  const publishedLessons = data?.lessons.filter((l) => l.status === 'published').length ?? 0
  const topbarMeta = data
    ? [
        'Конструктор',
        `${data.lessons.length} ${data.lessons.length === 1 ? 'урок' : data.lessons.length < 5 ? 'урока' : 'уроков'}`,
        data.audience_id === null ? 'виден всем сотрудникам' : 'настроена аудитория',
      ].join(' · ')
    : ''

  return (
    <div className={isDesktop ? undefined : 'mx-auto max-w-3xl'}>
      {!isDesktop && (
        <MobilePageHeader eyebrow="Конструктор" title={data?.title ?? 'Курс'} />
      )}
      {/* Десктопный топбар по макету «Конструктор»: назад-чип, название и
          мета, бейдж статуса, действия курса — lifecycle тут, а не в карточке
          настроек; в карточке остаются сохранение и удаление. */}
      {isDesktop && data && (
        <div className="sticky top-0 z-10 flex flex-wrap items-center gap-x-3.5 gap-y-2 border-b border-hair bg-bg px-5 py-3">
          <Link
            to="/learn/courses"
            className="inline-flex h-9 shrink-0 items-center gap-[7px] rounded-[10px] border border-glass-border px-3 text-[13px] font-semibold text-text2 hover:text-text"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2.2} /> {coursesTitle}
          </Link>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[14px] font-semibold text-text">{data.title}</p>
            <p className="mt-px truncate text-[12px] text-text2">{topbarMeta}</p>
          </div>
          <Badge variant={data.status === 'published' ? 'default' : 'outline'} className="shrink-0">
            {CONTENT_STATUS_LABEL[data.status]}
          </Badge>
          {/* Действия переносятся внутрь бара, а не распирают его: на 1280 с
              сайдбаром main уходил в горизонтальный скролл (QA-0821 #19). */}
          <div className="flex min-w-0 flex-wrap justify-end gap-2">
            <Button
              variant="secondary"
              size="md"
              className="bg-transparent"
              title={publishedLessons === 0 ? 'Опубликуйте хотя бы один урок — иначе сотруднику нечего смотреть' : undefined}
              onClick={() => navigate(`/learn/courses/${data.id}?preview=1`)}
            >
              <Eye className="h-4 w-4" /> Глазами сотрудника
            </Button>
            <Button
              variant="secondary"
              size="md"
              className="bg-transparent"
              disabled={duplicate.isPending}
              onClick={() =>
                void duplicate
                  .mutateAsync(undefined as never)
                  .then((copy) => {
                    toast.success('Дубликат создан черновиком')
                    navigate(`/learn/courses/${copy.id}/edit`)
                  })
                  .catch(() => undefined)
              }
            >
              <Copy className="h-4 w-4" /> Дубликат
            </Button>
            <Button variant="secondary" size="md" className="bg-transparent" onClick={() => setAudienceOpen(true)}>
              <Users className="h-4 w-4" /> Аудитория
            </Button>
            <Button variant="secondary" size="md" className="bg-transparent" onClick={() => setAssignOpen(true)}>
              <UserPlus className="h-4 w-4" /> Назначить
            </Button>
            {STATUS_ACTIONS[data.status].map((action) => (
              <Button
                key={action.to}
                size="md"
                variant={action.to === 'published' ? 'default' : 'secondary'}
                className={action.to === 'published' ? undefined : 'bg-transparent'}
                disabled={setStatus.isPending || (action.to === 'published' && publishedLessons === 0)}
                title={
                  action.to === 'published' && publishedLessons === 0
                    ? 'Курс нельзя опубликовать без хотя бы одного опубликованного урока'
                    : undefined
                }
                onClick={() =>
                  void setStatus
                    .mutateAsync(action.to)
                    .then(() => toast.success(CONTENT_STATUS_LABEL[action.to]))
                    .catch(() => undefined)
                }
              >
                {action.label}
              </Button>
            ))}
          </div>
        </div>
      )}
      <div className={isDesktop ? 'mx-auto flex max-w-[760px] flex-col gap-4 px-5 pb-16 pt-8' : 'space-y-4 p-4'}>
        {!isDesktop && (
          <Link
            to="/learn/courses"
            className="inline-flex min-h-11 items-center gap-1.5 text-sm text-text2 hover:text-text"
          >
            <ArrowLeft className="h-4 w-4" /> {coursesTitle}
          </Link>
        )}

        {course.isLoading && <SkeletonRows rows={6} />}
        {course.isError && <QueryError onRetry={() => void course.refetch()} />}

        {data && (
          <>
            <CourseSettingsCard
              course={data}
              compact={isDesktop}
              publishedLessons={publishedLessons}
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
                progressionMode={data.progression_mode}
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
  compact,
  publishedLessons,
  onAudience,
  onAssign,
}: {
  course: CourseDetail
  /** Десктоп: lifecycle/аудитория/назначения живут в топбаре — в карточке только сохранение и удаление. */
  compact: boolean
  publishedLessons: number
  onAudience: () => void
  onAssign: () => void
}) {
  const navigate = useNavigate()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [title, setTitle] = useState(course.title)
  const [description, setDescription] = useState(course.description ?? '')
  const [courseType, setCourseType] = useState<CourseType>(course.course_type)
  const [mode, setMode] = useState<ProgressionMode>(course.progression_mode)
  const [certificate, setCertificate] = useState(course.certificate_enabled)

  const save = useCourseMutation(() =>
    learnApi.updateCourse(course.id, {
      title: title.trim(),
      description: description.trim() || null,
      course_type: courseType,
      progression_mode: mode,
      certificate_enabled: certificate,
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
    mode !== course.progression_mode ||
    certificate !== course.certificate_enabled

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
            {/* Свободный режим отключает замки уроков целиком: сервер
                (`_lesson_blocker`) даже не смотрит на unlock_rule. Автор курса
                об этом не знал и выставлял «После предыдущего», ожидая, что
                тест откроет следующий урок. */}
            {mode === 'free' && (
              <p className="mt-1 text-[13px] leading-[1.45] text-text2">
                Все уроки открыты сразу — правила доступа внутри уроков не
                действуют.
              </p>
            )}
          </div>
        </div>
        <label className="flex items-center gap-2 pt-1 text-xs text-text2">
          <Switch checked={certificate} onCheckedChange={setCertificate} />
          выдавать сертификат за прохождение курса
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-glass-border pt-3">
        {dirty && (
          <Button
            size="sm"
            disabled={!title.trim() || save.isPending}
            onClick={() =>
              void save.mutateAsync(undefined as never).then(() => toast.success('Сохранено'))
              .catch(() => undefined)
            }
          >
            Сохранить
          </Button>
        )}
        {!compact &&
          STATUS_ACTIONS[course.status].map((action) => (
            <Button
              key={action.to}
              size="sm"
              variant={action.to === 'published' ? 'default' : 'secondary'}
              disabled={setStatus.isPending || (action.to === 'published' && publishedLessons === 0)}
              onClick={() =>
                void setStatus
                  .mutateAsync(action.to)
                  .then(() => toast.success(CONTENT_STATUS_LABEL[action.to]))
                  .catch(() => undefined)
              }
            >
              {action.label}
            </Button>
          ))}
        {!compact && (
          <Button size="sm" variant="secondary" onClick={onAudience}>
            <Users className="h-4 w-4" /> Аудитория
          </Button>
        )}
        {!compact && (
          <Button size="sm" variant="secondary" onClick={onAssign}>
            <UserPlus className="h-4 w-4" /> Назначить
          </Button>
        )}
        <span className="flex-1" />
        {course.published_at === null && (
          <Button
            size="sm"
            variant="secondary"
            className="bg-transparent text-red"
            disabled={remove.isPending}
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 className="h-4 w-4" /> Удалить
          </Button>
        )}
      </div>
      <p className="text-[12px] leading-[1.5] text-text2">
        {publishedLessons === 0 && 'Курс нельзя опубликовать без хотя бы одного опубликованного урока. '}
        Удалить можно только курс, который никогда не публиковался. Публиковавшийся — в архив.
      </p>
      {deleteOpen && (
        <ResponsiveDialog
          open
          onOpenChange={(v) => !v && setDeleteOpen(false)}
          title={`Удалить курс «${course.title}»?`}
          description="Уроки и тесты черновика удалятся насовсем. Назначений и прогресса у непубликовавшегося курса нет."
          desktopWidth={440}
          footer={
            <>
              <Button variant="secondary" onClick={() => setDeleteOpen(false)} disabled={remove.isPending}>
                Отмена
              </Button>
              <Button
                variant="destructive"
                disabled={remove.isPending}
                onClick={() =>
                  void remove
                    .mutateAsync(undefined as never)
                    .then(() => navigate('/learn/courses'))
                    .catch(() => undefined)
                }
              >
                Удалить
              </Button>
            </>
          }
        >
          <span className="sr-only">Подтверждение удаления</span>
        </ResponsiveDialog>
      )}
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
              .catch(() => undefined)
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
              .catch(() => undefined)
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
  const [deleteOpen, setDeleteOpen] = useState(false)

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
      {/* Иконка = ДЕЙСТВИЕ (как у кнопки в редакторе), состояние — бейдж рядом. */}
      <button
        type="button"
        title={lesson.status === 'published' ? 'Скрыть от сотрудников' : 'Опубликовать'}
        aria-label={lesson.status === 'published' ? 'Скрыть от сотрудников' : 'Опубликовать'}
        disabled={toggle.isPending}
        onClick={() => void toggle.mutateAsync(undefined as never)}
        className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text"
      >
        {lesson.status === 'published' ? (
          <EyeOff className="h-4 w-4" />
        ) : (
          <Eye className="h-4 w-4" />
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
        aria-label={`Удалить урок «${lesson.title}»`}
        disabled={remove.isPending}
        onClick={() => setDeleteOpen(true)}
        className="rounded p-1.5 text-text3 hover:bg-glass hover:text-red"
      >
        <Trash2 className="h-4 w-4" />
      </button>
      {deleteOpen && (
        <ResponsiveDialog
          open
          onOpenChange={(v) => !v && setDeleteOpen(false)}
          title={`Удалить урок «${lesson.title}»?`}
          description="Содержимое урока и его тест удалятся. Прогресс сотрудников по этому уроку перестанет учитываться."
          desktopWidth={440}
          footer={
            <>
              <Button variant="secondary" onClick={() => setDeleteOpen(false)} disabled={remove.isPending}>
                Отмена
              </Button>
              <Button
                variant="destructive"
                disabled={remove.isPending}
                onClick={() => void remove.mutateAsync(undefined as never).then(() => setDeleteOpen(false))}
              >
                Удалить
              </Button>
            </>
          }
        >
          <span className="sr-only">Подтверждение удаления</span>
        </ResponsiveDialog>
      )}
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
  const audience = useAudienceDraft(course.audience_id)
  const { value, setValue } = audience
  const save = useCourseMutation(() => learnApi.setCourseAudience(course.id, value))
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Кому виден «{course.title}»</DialogTitle>
        </DialogHeader>
        {audience.loading ? (
          <SkeletonRows rows={3} />
        ) : (
          <>
            {audience.failed && (
              <p className="text-sm text-red">
                Не удалось загрузить текущие правила — сохранение перезапишет их.
              </p>
            )}
            <AudiencePicker
              value={value}
              onChange={setValue}
              extraLabels={audience.extraLabels}
            />
          </>
        )}
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            type="button"
            disabled={save.isPending || !audience.ready}
            onClick={() =>
              void save.mutateAsync(undefined as never).then(() => {
                toast.success('Аудитория обновлена')
                onClose()
              })
              .catch(() => undefined)
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
              .catch(() => undefined)
            }
          >
            Назначить ({selected.size})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
