import { CalendarClock, Check, GraduationCap, Pencil, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
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
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useCourseMutation, useCourses } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
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

/**
 * «Моё обучение» (Ф3a): каталог видимых курсов = mandatory по аудитории ∪
 * личные назначения. Управление курсами — в /learn/admin/courses (Ф3a.7).
 */

function dueLabel(iso: string): { text: string; overdue: boolean } {
  const due = new Date(iso)
  const overdue = due.getTime() < Date.now()
  return {
    text: due.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' }),
    overdue,
  }
}

function CourseCard({ course, manage }: { course: Course; manage?: boolean }) {
  const navigate = useNavigate()
  const pct =
    course.lessons_total > 0
      ? Math.round((course.lessons_completed / course.lessons_total) * 100)
      : 0
  const due = course.due_at ? dueLabel(course.due_at) : null

  return (
    <Link
      to={`/learn/courses/${course.id}`}
      className="block rounded-xl border border-glass-border bg-glass p-4 transition-colors hover:border-amber/50"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant={course.course_type === 'mandatory' ? 'default' : 'secondary'}>
              {COURSE_TYPE_LABEL[course.course_type]}
            </Badge>
            {due && !course.completed && (
              <span
                className={cn(
                  'inline-flex items-center gap-1 text-xs',
                  due.overdue ? 'text-red' : 'text-text3',
                )}
              >
                <CalendarClock className="h-3.5 w-3.5" />
                до {due.text}
              </span>
            )}
          </div>
          <h3 className="mt-1.5 truncate font-display text-base font-semibold text-text">
            {course.title}
          </h3>
          {course.description && (
            <p className="mt-0.5 line-clamp-2 text-sm text-text2">{course.description}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {manage && (
            <button
              type="button"
              title="Редактировать курс"
              onClick={(e) => {
                e.preventDefault()
                navigate(`/learn/courses/${course.id}/edit`)
              }}
              className="rounded p-1.5 text-text3 hover:bg-surface hover:text-text"
            >
              <Pencil className="h-4 w-4" />
            </button>
          )}
          {course.completed && (
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-green/15">
              <Check className="h-4 w-4 text-green" />
            </span>
          )}
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface">
          <span
            className={cn('block h-full rounded-full', course.completed ? 'bg-green' : 'bg-amber')}
            style={{ width: `${course.completed ? 100 : pct}%` }}
          />
        </span>
        <span className="shrink-0 text-xs text-text3">
          {course.completed
            ? 'Пройден'
            : `${course.lessons_completed}/${course.lessons_total} уроков`}
        </span>
      </div>
    </Link>
  )
}

export function LearnCoursesPage() {
  const isDesktop = useIsDesktop()
  const [createOpen, setCreateOpen] = useState(false)

  const probe = useCourses(false)
  const canManage =
    probe.data !== undefined &&
    ['admin', 'publisher', 'author'].includes(probe.data.content_role)
  const managed = useCourses(true, canManage)

  const items = probe.data?.items ?? []
  const active = items.filter((c) => !c.completed)
  const done = items.filter((c) => c.completed)
  // «Управление» — курсы вне личного каталога (черновики, архив, чужие аудитории).
  const consumerIds = new Set(items.map((c) => c.id))
  const managedOnly = (managed.data?.items ?? []).filter((c) => !consumerIds.has(c.id))

  return (
    <div className="mx-auto max-w-3xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Моё обучение" />}
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex items-center justify-between gap-2">
          {isDesktop && (
            <h1 className="font-display text-2xl font-bold text-text">Моё обучение</h1>
          )}
          {canManage && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" /> Курс
            </Button>
          )}
        </div>

        {probe.isLoading && <SkeletonRows rows={4} />}
        {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}

        {probe.data && items.length === 0 && (
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <GraduationCap className="mx-auto h-8 w-8 text-text3" />
            <p className="mt-3 text-sm text-text2">
              Вам пока не назначено ни одного курса.
            </p>
          </div>
        )}

        {active.length > 0 && (
          <div className="space-y-3">
            {active.map((c) => (
              <CourseCard key={c.id} course={c} manage={canManage} />
            ))}
          </div>
        )}

        {done.length > 0 && (
          <div className="space-y-3">
            <p className="pt-2 text-[11px] font-semibold uppercase tracking-wider text-text3">
              Пройденные
            </p>
            {done.map((c) => (
              <CourseCard key={c.id} course={c} manage={canManage} />
            ))}
          </div>
        )}

        {canManage && managedOnly.length > 0 && (
          <div className="space-y-2">
            <p className="pt-2 text-[11px] font-semibold uppercase tracking-wider text-text3">
              Управление контентом
            </p>
            {managedOnly.map((c) => (
              <Link
                key={c.id}
                to={`/learn/courses/${c.id}/edit`}
                className="flex items-center gap-2 rounded-lg border border-glass-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:border-amber/50"
              >
                <span className="min-w-0 flex-1 truncate">{c.title}</span>
                <Badge variant="secondary">{CONTENT_STATUS_LABEL[c.status]}</Badge>
                <Pencil className="h-4 w-4 shrink-0 text-text3" />
              </Link>
            ))}
          </div>
        )}

        {createOpen && <CreateCourseDialog onClose={() => setCreateOpen(false)} />}
      </div>
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
