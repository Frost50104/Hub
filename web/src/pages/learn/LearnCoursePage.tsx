import {
  ArrowLeft,
  Award,
  CalendarClock,
  Check,
  CircleDashed,
  Lock,
  Play,
} from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useCourse, useMyCertificates } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { COURSE_TYPE_LABEL, type LessonMeta } from '@/lib/learn'

/** Карточка курса (Ф3a): уроки с серверными замками + «Продолжить». */

function LessonRow({ lesson, index }: { lesson: LessonMeta; index: number }) {
  const inner = (
    <div
      className={cn(
        'flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-colors',
        lesson.locked
          ? 'cursor-default border-glass-border bg-surface/50 opacity-60'
          : 'border-glass-border bg-glass hover:border-amber/50',
      )}
    >
      <span
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
          lesson.completed
            ? 'bg-green/15 text-green'
            : lesson.locked
              ? 'bg-surface text-text3'
              : 'bg-amber/15 text-amber',
        )}
      >
        {lesson.completed ? (
          <Check className="h-3.5 w-3.5" />
        ) : lesson.locked ? (
          <Lock className="h-3.5 w-3.5" />
        ) : (
          index + 1
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className={cn('truncate text-sm font-medium', lesson.locked ? 'text-text3' : 'text-text')}>
          {lesson.title}
        </p>
        <p className="text-xs text-text3">
          {lesson.status === 'draft'
            ? 'Черновик — виден только редакторам'
            : lesson.completed
              ? 'Пройден'
              : lesson.locked
                ? 'Откроется после предыдущих уроков'
                : lesson.started
                  ? 'В процессе'
                  : lesson.content_format === 'pdf'
                    ? 'Документ PDF'
                    : 'Не начат'}
        </p>
      </div>
      {lesson.status === 'draft' && <Badge variant="outline">черновик</Badge>}
      {!lesson.locked && !lesson.completed && (
        <Play className="h-4 w-4 shrink-0 text-text3" />
      )}
    </div>
  )

  if (lesson.locked) return inner
  return <Link to={`/learn/lessons/${lesson.id}`}>{inner}</Link>
}

export function LearnCoursePage() {
  const { courseId } = useParams<{ courseId: string }>()
  const isDesktop = useIsDesktop()
  const navigate = useNavigate()
  const course = useCourse(courseId)
  const certificates = useMyCertificates()

  const data = course.data
  const myCert = certificates.data?.find((c) => c.course_id === courseId) ?? null
  const published = (data?.lessons ?? []).filter((lesson) => lesson.status === 'published')
  const next = published.find((lesson) => !lesson.completed && !lesson.locked)
  const pct =
    data && data.lessons_total > 0
      ? Math.round((data.lessons_completed / data.lessons_total) * 100)
      : 0

  return (
    <div className="mx-auto max-w-3xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title={data?.title ?? 'Курс'} />}
      {!isDesktop && (
        <div className="px-4">
          <Link
            to="/learn/courses"
            className="inline-flex items-center gap-1.5 text-sm text-text3 hover:text-text"
          >
            <ArrowLeft className="h-4 w-4" /> Моё обучение
          </Link>
        </div>
      )}
      <div className="space-y-4 p-4 lg:p-8">
        {isDesktop && (
          <Link
            to="/learn/courses"
            className="inline-flex items-center gap-1.5 text-sm text-text3 hover:text-text"
          >
            <ArrowLeft className="h-4 w-4" /> Моё обучение
          </Link>
        )}

        {course.isLoading && <SkeletonRows rows={5} />}
        {course.isError && <QueryError onRetry={() => void course.refetch()} />}

        {data && (
          <>
            <div className="rounded-xl border border-glass-border bg-glass p-4 lg:p-5">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge variant={data.course_type === 'mandatory' ? 'default' : 'secondary'}>
                  {COURSE_TYPE_LABEL[data.course_type]}
                </Badge>
                {data.due_at && !data.completed && (
                  <span className="inline-flex items-center gap-1 text-xs text-text3">
                    <CalendarClock className="h-3.5 w-3.5" />
                    завершить до{' '}
                    {new Date(data.due_at).toLocaleDateString('ru-RU', {
                      day: 'numeric',
                      month: 'long',
                    })}
                  </span>
                )}
              </div>
              {isDesktop && (
                <h1 className="mt-2 font-display text-2xl font-bold text-text">
                  {data.title}
                </h1>
              )}
              {data.description && (
                <p className="mt-1.5 whitespace-pre-wrap text-sm text-text2">
                  {data.description}
                </p>
              )}

              <div className="mt-3 flex items-center gap-2">
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface">
                  <span
                    className={cn(
                      'block h-full rounded-full',
                      data.completed ? 'bg-green' : 'bg-amber',
                    )}
                    style={{ width: `${data.completed ? 100 : pct}%` }}
                  />
                </span>
                <span className="shrink-0 text-xs text-text3">
                  {data.completed
                    ? 'Курс пройден'
                    : `${data.lessons_completed}/${data.lessons_total}`}
                </span>
              </div>

              {next && !data.completed && (
                <Button
                  className="mt-3"
                  onClick={() => navigate(`/learn/lessons/${next.id}`)}
                >
                  <Play className="h-4 w-4" />
                  {data.lessons_completed > 0 ? 'Продолжить обучение' : 'Начать обучение'}
                </Button>
              )}
              {data.completed && (
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <p className="inline-flex items-center gap-1.5 text-sm text-green">
                    <Check className="h-4 w-4" /> Все уроки пройдены
                  </p>
                  {myCert && (
                    <Link
                      to={`/learn/certificates/${myCert.id}`}
                      className="inline-flex items-center gap-1.5 text-sm text-amber hover:opacity-80"
                    >
                      <Award className="h-4 w-4" /> Сертификат
                    </Link>
                  )}
                </div>
              )}
            </div>

            <div className="space-y-2">
              {(data.lessons ?? []).length === 0 && (
                <div className="rounded-xl border border-glass-border bg-glass p-6 text-center">
                  <CircleDashed className="mx-auto h-6 w-6 text-text3" />
                  <p className="mt-2 text-sm text-text2">В курсе пока нет уроков.</p>
                </div>
              )}
              {data.lessons.map((lesson, i) => (
                <LessonRow key={lesson.id} lesson={lesson} index={i} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
