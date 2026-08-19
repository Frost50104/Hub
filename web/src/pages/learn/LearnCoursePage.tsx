import {
  ArrowLeft,
  Award,
  CalendarClock,
  Check,
  ChevronRight,
  CircleDashed,
  Lock,
  Play,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { courseTypeBadgeClass } from '@/components/learn/CourseCover'
import { QueryError } from '@/components/QueryError'
import { MetaLine } from '@/components/ui/MetaLine'
import { Skeleton } from '@/components/ui/Skeleton'
import { useCourse, useMyCertificates } from '@/hooks/useLearn'
import { cn } from '@/lib/cn'
import { COURSE_TYPE_LABEL, type CourseDetail, type LessonMeta } from '@/lib/learn'
import { formatMinutes, nbsp, plural } from '@/lib/typography'

/** Карточка курса (Ф3a): программа с серверными замками + «Продолжить». */

type RowKind = 'done' | 'current' | 'locked' | 'draft'

function rowKind(lesson: LessonMeta, isCurrent: boolean): RowKind {
  if (lesson.status === 'draft') return 'draft'
  if (lesson.completed) return 'done'
  if (lesson.locked) return 'locked'
  return isCurrent ? 'current' : 'locked'
}

/** Что обещает урок: длительность и чем он отличается от простого текста. */
function lessonExtras(lesson: LessonMeta): string[] {
  const out = [formatMinutes(lesson.estimated_minutes)]
  if (lesson.content_format === 'pdf') out.push('PDF')
  if (lesson.has_check_question) out.push('контрольный вопрос')
  if (lesson.has_quiz) out.push('тест')
  return out
}

function rowMeta(lesson: LessonMeta, kind: RowKind, index: number): string {
  if (kind === 'done') return 'Пройден'
  if (kind === 'draft') return 'Черновик — виден только редакторам'
  if (kind === 'current') {
    return [lesson.started ? 'В процессе' : 'Начать', ...lessonExtras(lesson)].join(' · ')
  }
  // Замок называет блокирующий урок по имени — тот же текст, что на
  // полноэкранном состоянии «урок заперт». Имя приходит с сервера: клиент не
  // знает, держит ли урок незавершённый предыдущий или несданный тест.
  return lesson.blocked_by_title
    ? `Откроется после урока ${index} — «${lesson.blocked_by_title}»`
    : 'Откроется после предыдущих уроков'
}

function LessonRow({
  lesson,
  index,
  kind,
}: {
  lesson: LessonMeta
  index: number
  kind: RowKind
}) {
  const inner = (
    <div
      className={cn(
        // Одна геометрия на все статусы — различаются рамка, фон и кружок.
        'flex min-h-[56px] items-center gap-3 rounded-xl px-3.5 py-3 text-left transition-colors',
        kind === 'current' && 'border border-l-[3px] border-amber/40 border-l-amber bg-amber/[0.06]',
        kind === 'draft' && 'border border-dashed border-glass-border',
        kind === 'locked' && 'cursor-not-allowed border border-hair',
        kind === 'done' && 'border border-hair hover:border-amber/40',
      )}
    >
      <span
        className={cn(
          'flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-full font-display text-xs font-bold',
          kind === 'done' && 'bg-green-deep text-bg',
          kind === 'current' && 'bg-amber text-on-amber',
          kind === 'draft' && 'border border-dashed border-glass-border text-text2',
          kind === 'locked' && 'bg-surface text-text2',
        )}
      >
        {kind === 'done' ? (
          <Check className="h-[15px] w-[15px]" strokeWidth={3} />
        ) : kind === 'locked' ? (
          <Lock className="h-3.5 w-3.5" />
        ) : (
          index
        )}
      </span>
      <span className="min-w-0 flex-1">
        {/* Запертая строка не гасится opacity: в светлой теме название урока
            падало бы до ~1,6:1. Тускнеет только кружок. */}
        <span
          className={cn(
            'block text-[15px] font-semibold leading-[1.4]',
            kind === 'locked' || kind === 'draft' ? 'text-text2' : 'text-text',
          )}
        >
          {lesson.title}
        </span>
        <span className="mt-0.5 block text-[13px] leading-[1.4] text-text2">
          {nbsp(rowMeta(lesson, kind, index - 1))}
        </span>
      </span>
      {kind !== 'locked' && <ChevronRight className="h-[18px] w-[18px] shrink-0 text-text2" />}
    </div>
  )

  if (kind === 'locked') return inner
  return <Link to={`/learn/lessons/${lesson.id}`}>{inner}</Link>
}

function CourseHeader({ data }: { data: CourseDetail }) {
  const published = data.lessons.filter((l) => l.status === 'published')
  const next = published.find((l) => !l.completed && !l.locked)
  const first = published[0]
  const pct =
    data.lessons_total > 0
      ? Math.round((data.lessons_completed / data.lessons_total) * 100)
      : 0
  const overdue = Boolean(
    data.due_at && !data.completed && new Date(data.due_at) < new Date(),
  )
  const target = data.completed ? first : (next ?? first)
  const targetIndex = target ? published.indexOf(target) + 1 : 0

  const deadline = data.due_at
    ? new Date(data.due_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
    : null

  return (
    <header className="px-5 pt-14">
      <Link
        to="/learn/courses"
        className="inline-flex h-11 items-center gap-1.5 text-[13px] font-semibold uppercase tracking-[0.06em] text-text2 hover:text-text"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={2.2} /> Моё обучение
      </Link>

      <div className="mb-2.5 mt-1 flex flex-wrap items-center gap-2.5">
        <span
          className={cn(
            'h-[22px] px-2 text-[11px]',
            overdue
              ? 'inline-flex items-center rounded-md bg-red font-bold uppercase tracking-[0.08em] text-bg'
              : courseTypeBadgeClass(data.course_type, data.completed),
          )}
        >
          {overdue ? 'Просрочено' : COURSE_TYPE_LABEL[data.course_type]}
        </span>
        {deadline && (
          <span
            className={cn(
              'inline-flex items-center gap-1.5 text-[13px]',
              overdue ? 'text-red' : data.completed ? 'text-green' : 'text-text2',
            )}
          >
            <CalendarClock className="h-3.5 w-3.5" />
            {nbsp(
              overdue
                ? `Дедлайн был ${deadline}`
                : data.completed
                  ? 'Курс пройден'
                  : `Завершить до ${deadline}`,
            )}
          </span>
        )}
      </div>

      <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text [text-wrap:balance] lg:text-[34px] lg:leading-[1.15]">
        {data.title}
      </h1>

      {data.description && (
        <p className="mt-3 whitespace-pre-wrap text-[17px] leading-[1.6] text-text2 [text-wrap:pretty] lg:text-[20px]">
          {data.description}
        </p>
      )}

      <MetaLine
        className="mt-3.5 text-sm text-text2"
        items={[
          plural(data.lessons_total, 'урок', 'урока', 'уроков'),
          data.quizzes_total > 0 && plural(data.quizzes_total, 'тест', 'теста', 'тестов'),
          data.estimated_minutes_total > 0 && formatMinutes(data.estimated_minutes_total),
        ].filter(Boolean)}
      />

      <div className="mt-5 flex items-center gap-3.5">
        <span className="block h-1.5 flex-1 overflow-hidden rounded-full bg-surface">
          <span
            className={cn(
              'block h-full rounded-full',
              // Цвет полосы задаёт состояние курса, а не экран: одинаково на
              // витрине, в каталоге и здесь.
              overdue ? 'bg-red' : data.completed ? 'bg-green' : 'bg-amber',
            )}
            style={{ width: `${data.completed ? 100 : pct}%` }}
          />
        </span>
        <span className="shrink-0 whitespace-nowrap font-display text-sm font-bold tabular-nums text-text lg:text-base">
          {data.completed ? 100 : pct}%
        </span>
      </div>
      <p className="mb-[18px] mt-2 text-sm text-text2">
        {nbsp(`${data.lessons_completed} из ${data.lessons_total} уроков`)}
      </p>

      {target && (
        <Link
          to={`/learn/lessons/${target.id}`}
          className={cn(
            'flex min-h-[56px] w-full items-center gap-3 rounded-xl px-[18px] text-left',
            data.completed
              ? 'border border-glass-border bg-surface text-text'
              : 'bg-amber text-on-amber',
          )}
        >
          <Play className="h-5 w-5 shrink-0" fill="currentColor" />
          <span className="min-w-0 flex-1">
            <span className="block text-[16px] font-semibold">
              {data.completed
                ? 'Пройти заново'
                : data.lessons_completed > 0
                  ? 'Продолжить обучение'
                  : 'Начать обучение'}
            </span>
            <span className="mt-px block truncate text-[13px] opacity-75">
              Урок {targetIndex} · {target.title}
            </span>
          </span>
        </Link>
      )}
    </header>
  )
}

export function LearnCoursePage() {
  const { courseId } = useParams<{ courseId: string }>()
  const course = useCourse(courseId)
  const certificates = useMyCertificates()

  const data = course.data
  const myCert = certificates.data?.find((c) => c.course_id === courseId) ?? null
  const published = (data?.lessons ?? []).filter((l) => l.status === 'published')
  const currentId = published.find((l) => !l.completed && !l.locked)?.id

  return (
    <div className="mx-auto max-w-[680px]">
      {course.isLoading && (
        <div className="space-y-4 px-5 pt-14">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-[30px] w-3/4" />
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-2/3" />
          <Skeleton className="h-[56px] w-full" />
          <div className="space-y-2 pt-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-[56px] w-full" />
            ))}
          </div>
        </div>
      )}
      {course.isError && (
        <div className="p-5">
          <QueryError onRetry={() => void course.refetch()} />
        </div>
      )}

      {data && (
        <>
          <CourseHeader data={data} />

          <div className="flex flex-col gap-3.5 px-5 pb-8 pt-6">
            {data.completed && myCert && (
              <Link
                to={`/learn/certificates/${myCert.id}`}
                className="flex items-center gap-3.5 rounded-[14px] border border-amber/35 bg-amber/[0.08] p-4"
              >
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-amber text-on-amber">
                  <Award className="h-6 w-6" strokeWidth={1.9} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[16px] font-semibold text-text">
                    Сертификат готов
                  </span>
                  <span className="mt-0.5 block text-sm text-text2">
                    {nbsp(
                      `Выдан ${new Date(myCert.issued_at).toLocaleDateString('ru-RU', {
                        day: 'numeric',
                        month: 'long',
                        year: 'numeric',
                      })} · № ${myCert.serial}`,
                    )}
                  </span>
                </span>
                <ChevronRight className="h-[18px] w-[18px] shrink-0 text-text2" />
              </Link>
            )}

            <p className="mt-1.5 text-xs font-bold uppercase tracking-[0.09em] text-text2">
              Программа курса
            </p>

            {data.lessons.length === 0 && (
              <div className="rounded-[14px] border border-hair p-6 text-center">
                <CircleDashed className="mx-auto h-6 w-6 text-text2" />
                <p className="mt-2 text-[15px] text-text2">В курсе пока нет уроков.</p>
              </div>
            )}

            <div className="flex flex-col gap-2">
              {data.lessons.map((lesson, i) => (
                <LessonRow
                  key={lesson.id}
                  lesson={lesson}
                  index={i + 1}
                  kind={rowKind(lesson, lesson.id === currentId)}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
