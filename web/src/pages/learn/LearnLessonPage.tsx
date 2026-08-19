import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronLeft,
  CircleAlert,
  ExternalLink,
  FileText,
  Lock,
  Trophy,
} from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { LessonRenderer } from '@/components/learn/lesson/LessonRenderer'
import {
  extractSections,
  LessonSections,
} from '@/components/learn/lesson/LessonSections'
import { QuizRunner } from '@/components/learn/lesson/QuizRunner'
import { flushVideoProgress } from '@/components/learn/lesson/VideoPlayer'
import { Skeleton } from '@/components/ui/Skeleton'
import { useCourse, useLesson } from '@/hooks/useLearn'
import { useScrollProgress } from '@/hooks/useScrollProgress'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import { learnApi, type LessonContent, type LessonMeta } from '@/lib/learn'
import { formatMinutes, plural } from '@/lib/typography'

/**
 * Прохождение урока (Ф3a) — учебная среда, а не строка списка.
 *
 * «Завершить урок» — явное действие; сервер проверяет предусловия
 * (gate-вопросы + досмотр видео ≥90%) и вернёт 409 с человекочитаемой
 * причиной — локальный чек-лист лишь подсказывает, поэтому кнопка остаётся
 * кликабельной при невыполненных условиях.
 */

const WATCH_THRESHOLD = 0.9
/** Порог появления мини-шапки — ~96px прокрутки, как в макете. */
const MINI_HEADER_AT = 96

// pdf.js — тяжёлый lazy-чанк (вне PWA-precache, см. globIgnores vite.config).
// Имя чанка PdfViewer-*.js обязано сохраниться: на него завязан globIgnores.
const PdfViewer = lazy(() => import('@/components/learn/lesson/PdfViewer'))

function isLockedError(err: unknown): boolean {
  return (err as { response?: { status?: number } }).response?.status === 403
}

/** Кружок-галочка чек-листа: выполненное зачёркнуто, а не выкрашено ниже нормы. */
function GateRow({ done, label }: { done: boolean; label: string }) {
  return (
    <li className="flex items-start gap-2.5">
      <span
        className={cn(
          'mt-px flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full',
          done ? 'bg-green-deep text-bg' : 'border border-glass-border text-transparent',
        )}
      >
        <Check className="h-3 w-3" strokeWidth={3} />
      </span>
      <span
        className={cn(
          'text-[15px] leading-[1.5]',
          done ? 'text-text2 line-through' : 'text-text',
        )}
      >
        {label}
      </span>
    </li>
  )
}

function gateRows(
  lesson: LessonContent,
  answeredGates: Set<string>,
  videoCoverage: Record<string, number>,
): { label: string; done: boolean }[] {
  const rows: { label: string; done: boolean }[] = []
  if (lesson.gate_blocks.length) {
    const gatesDone = lesson.gate_blocks.filter((b) => answeredGates.has(b)).length
    rows.push({
      label:
        lesson.gate_blocks.length === 1
          ? 'Ответить на контрольный вопрос'
          : `Ответить на контрольные вопросы (${gatesDone} из ${lesson.gate_blocks.length})`,
      done: gatesDone >= lesson.gate_blocks.length,
    })
  }
  if (lesson.required_videos.length) {
    const videosDone = lesson.required_videos.filter(
      (m) => (videoCoverage[m] ?? 0) >= WATCH_THRESHOLD,
    ).length
    rows.push({
      label:
        lesson.required_videos.length === 1
          ? 'Досмотреть видео — минимум 90%'
          : `Досмотреть видео (${videosDone} из ${lesson.required_videos.length})`,
      done: videosDone >= lesson.required_videos.length,
    })
  }
  return rows
}

/** Полноэкранное состояние — загрузка, ошибка, замок. */
function LessonState({
  icon,
  tone = 'neutral',
  title,
  text,
  action,
}: {
  icon: ReactNode
  tone?: 'neutral' | 'error'
  title: string
  text: string
  action?: ReactNode
}) {
  return (
    <div className="px-5 py-14 text-center">
      <span
        className={cn(
          'mx-auto flex h-14 w-14 items-center justify-center rounded-2xl',
          tone === 'error' ? 'bg-red/[0.12] text-red' : 'bg-surface text-text2',
        )}
      >
        {icon}
      </span>
      <h2 className="mt-4 font-display text-xl font-bold leading-[1.25] text-text lg:text-2xl lg:leading-[1.22]">
        {title}
      </h2>
      <p className="mx-auto mt-2 max-w-[420px] text-[15px] leading-[1.55] text-text2 [text-wrap:pretty]">
        {text}
      </p>
      {action && <div className="mt-5 flex flex-col items-center gap-3">{action}</div>}
    </div>
  )
}

export function LearnLessonPage() {
  const { lessonId } = useParams<{ lessonId: string }>()
  const qc = useQueryClient()
  const lesson = useLesson(lessonId)
  const progress = useScrollProgress()

  const [answeredExtra, setAnsweredExtra] = useState<Set<string>>(new Set())
  const [liveCoverage, setLiveCoverage] = useState<Record<string, number>>({})

  // ОС 19.08: «Следующий урок» открывал следующий урок в самом низу. Роут тот
  // же (/learn/lessons/:lessonId), компонент не размонтируется, а SPA-переход
  // позицию скролла не трогает — сбрасываем сами, через фактический контейнер.
  const { scrollToTop } = progress
  useEffect(() => {
    scrollToTop()
  }, [lessonId, scrollToTop])

  const data = lesson.data

  // Курс нужен всей шапке: название, «урок N из M», имена соседних уроков и
  // оценка чтения. Запрос кэшируется TanStack Query по курсу, поэтому при
  // переходе между уроками одного курса он не повторяется.
  const course = useCourse(data?.course_id)

  const lessons: LessonMeta[] = useMemo(
    () => (course.data?.lessons ?? []).filter((l) => l.status === 'published'),
    [course.data],
  )
  const currentIndex = lessons.findIndex((l) => l.id === lessonId)
  const currentMeta = currentIndex >= 0 ? lessons[currentIndex] : undefined
  const prevMeta = data?.prev_lesson_id
    ? lessons.find((l) => l.id === data.prev_lesson_id)
    : undefined
  const nextMeta = data?.next_lesson_id
    ? lessons.find((l) => l.id === data.next_lesson_id)
    : undefined

  const overdue = Boolean(
    course.data?.due_at &&
      !course.data.completed &&
      new Date(course.data.due_at) < new Date(),
  )

  const answeredGates = useMemo(() => {
    const set = new Set(answeredExtra)
    for (const key of Object.keys(data?.block_state.answers ?? {})) set.add(key)
    return set
  }, [data, answeredExtra])

  const videoCoverage = useMemo(() => {
    const out: Record<string, number> = {}
    const saved = data?.block_state.video ?? {}
    for (const [mediaId, entry] of Object.entries(saved)) {
      const watched = entry.intervals.reduce((acc, [s, e]) => acc + (e - s), 0)
      out[mediaId] = entry.duration > 0 ? Math.min(1, watched / entry.duration) : 0
    }
    return { ...out, ...liveCoverage }
  }, [data, liveCoverage])

  const complete = useMutation({
    // Сначала дослать прогресс видео, потом просить завершение: покрытие
    // уходит на сервер раз в 15 секунд, и кнопка, нажатая сразу после
    // последнего кадра, судилась по устаревшим интервалам (ОС 19.08).
    mutationFn: async () => {
      await flushVideoProgress(lessonId!)
      return learnApi.completeLesson(lessonId!)
    },
    meta: { suppressGlobalError: true },
    onSuccess: (fresh) => {
      qc.setQueryData(['learn-lesson', lessonId], fresh)
      void qc.invalidateQueries({ queryKey: ['learn-course'] })
      void qc.invalidateQueries({ queryKey: ['learn-courses'] })
      toast.success(
        fresh.next_lesson_id === null
          ? 'Урок пройден — это был последний урок курса'
          : 'Урок пройден',
      )
    },
    onError: (err) => {
      toast.error('Урок ещё не завершён', { description: extractErrorDetail(err) })
    },
  })

  const rows = data ? gateRows(data, answeredGates, videoCoverage) : []
  const localReady = rows.every((r) => r.done)
  const courseHref = data ? `/learn/courses/${data.course_id}` : '/learn/courses'
  const showMini = progress.top > MINI_HEADER_AT

  const sections = useMemo(
    () => (data?.content ? extractSections(data.content) : []),
    [data],
  )

  return (
    <div className="relative mx-auto max-w-[680px] lg:flex lg:max-w-[960px] lg:gap-10 lg:px-4">
      <div className="min-w-0 lg:flex-1">
      {/* Мини-шапка приезжает после ~96px: до этого крупная шапка ещё на
          экране. h-0 — она оверлей, а не блок в потоке: иначе скрытая шапка
          отжимала бы крупную вниз на свою высоту. */}
      {data && (
        <div
          className={cn(
            'sticky top-0 z-20 h-0 transition-[opacity,transform] duration-[180ms] ease-out',
            showMini
              ? 'translate-y-0 opacity-100'
              : 'pointer-events-none -translate-y-2 opacity-0',
          )}
        >
          <div className="flex items-center gap-2.5 border-b border-hair bg-bg px-3 pb-2.5 pt-2 backdrop-blur-[14px]">
            <Link
              to={courseHref}
              aria-label={`К курсу «${course.data?.title ?? ''}»`}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-text2 hover:text-text"
            >
              <ChevronLeft className="h-[22px] w-[22px]" />
            </Link>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[11px] font-semibold uppercase tracking-[0.1em] text-text2">
                {course.data?.title ?? ' '}
              </p>
              <p className="truncate text-sm font-medium text-text">
                {data.title}
                {currentIndex >= 0 && ` · урок ${currentIndex + 1} из ${lessons.length}`}
              </p>
            </div>
            {overdue ? (
              <span className="shrink-0 rounded-md bg-red px-2 py-[3px] text-[11px] font-bold uppercase tracking-[0.08em] text-bg">
                Просрочено
              </span>
            ) : (
              <span className="shrink-0 font-display text-[13px] font-bold tabular-nums text-text2">
                {Math.round(progress.pct)}%
              </span>
            )}
          </div>
          {/* Нить прогресса — индикатор, поэтому без радиуса. */}
          <div className="h-0.5 bg-surface">
            <div
              className={cn('h-full transition-[width]', overdue ? 'bg-red' : 'bg-amber')}
              style={{ width: `${progress.pct}%` }}
            />
          </div>
        </div>
      )}

      <article ref={progress.ref}>
        {data?.status === 'draft' && (
          <div className="mx-5 mt-4 rounded-lg border border-dashed border-glass-border px-3 py-2 text-center text-[13px] text-text2">
            Черновик — виден только редакторам
          </div>
        )}

        {lesson.isLoading && (
          <div className="space-y-4 px-5 pt-14">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-[30px] w-3/4" />
            <Skeleton className="h-[30px] w-1/2" />
            <div className="space-y-2 pt-4">
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-3.5 w-2/3" />
            </div>
            <Skeleton className="h-[200px] w-full" />
          </div>
        )}

        {lesson.isError &&
          (isLockedError(lesson.error) ? (
            <LessonState
              icon={<Lock className="h-6 w-6" />}
              title="Урок пока закрыт"
              text="Он откроется, когда вы завершите предыдущий урок курса."
              action={
                <Link
                  to={courseHref}
                  className="inline-flex h-12 items-center justify-center rounded-xl bg-amber px-5 text-[15px] font-semibold text-on-amber"
                >
                  К программе курса
                </Link>
              }
            />
          ) : (
            <LessonState
              icon={<CircleAlert className="h-6 w-6" />}
              tone="error"
              title="Не удалось загрузить урок"
              text="Проверьте соединение и попробуйте ещё раз. Прогресс сохранён."
              action={
                <>
                  <button
                    type="button"
                    onClick={() => void lesson.refetch()}
                    className="inline-flex h-12 items-center justify-center rounded-xl bg-amber px-5 text-[15px] font-semibold text-on-amber"
                  >
                    Повторить
                  </button>
                  <Link to={courseHref} className="text-[15px] text-text2 hover:text-text">
                    К курсу
                  </Link>
                </>
              }
            />
          ))}

        {data && (
          <>
            <header className="px-5 pt-14">
              <Link
                to={courseHref}
                className="inline-flex h-11 items-center gap-1.5 text-[13px] font-semibold uppercase tracking-[0.06em] text-text2 hover:text-text"
              >
                <ArrowLeft className="h-4 w-4" strokeWidth={2.2} />
                {course.data?.title ?? 'К курсу'}
              </Link>
              <p className="mb-2 mt-0.5 flex items-center gap-2 text-[13px] text-text2">
                {currentIndex >= 0 && (
                  <>
                    <span className="font-semibold">
                      Урок {currentIndex + 1} из {lessons.length}
                    </span>
                    <span className="h-[3px] w-[3px] rounded-full bg-text3" />
                  </>
                )}
                <span>{formatMinutes(currentMeta?.estimated_minutes ?? 1)} чтения</span>
              </p>
              <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text [text-wrap:balance] lg:text-[34px] lg:leading-[1.15]">
                {data.title}
              </h1>
              {overdue && course.data?.due_at && (
                <p className="mt-2 text-[15px] text-red">
                  Дедлайн был{' '}
                  {new Date(course.data.due_at).toLocaleDateString('ru-RU', {
                    day: 'numeric',
                    month: 'long',
                  })}
                </p>
              )}
              <div className="mt-5 h-px bg-hair" />
            </header>

            <div className="px-5 pt-9">
              {data.content_format === 'pdf' && data.pdf_url && (
                <div className="space-y-2">
                  {/* pdf.js вместо iframe: Android Chrome не рендерит PDF во
                      встраиваниях, iOS показывал только первую страницу. */}
                  <Suspense fallback={<Skeleton className="h-[70vh] w-full rounded-xl" />}>
                    <PdfViewer
                      src={data.pdf_url}
                      title={data.title}
                      fallbackHref={!data.forbid_download ? data.pdf_url : undefined}
                    />
                  </Suspense>
                  {!data.forbid_download && (
                    <a
                      href={data.pdf_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 text-[15px] text-amber hover:opacity-80"
                    >
                      <FileText className="h-4 w-4" /> Открыть в новой вкладке
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>
              )}

              {data.content_format === 'blocks' && (
                <LessonRenderer
                  lesson={data}
                  onBlockAnswered={(blockId) =>
                    setAnsweredExtra((prev) => new Set(prev).add(blockId))
                  }
                  onVideoCoverage={(mediaId, c) =>
                    setLiveCoverage((prev) =>
                      (prev[mediaId] ?? 0) >= c ? prev : { ...prev, [mediaId]: c },
                    )
                  }
                />
              )}

              <QuizRunner lessonId={data.id} />
            </div>

            <div className="px-5 pb-8 pt-6">
              {data.completed ? (
                <div className="flex items-center gap-3 rounded-[14px] border border-green/35 bg-green/[0.09] p-4">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-green-deep text-bg">
                    <Check className="h-5 w-5" strokeWidth={2.6} />
                  </span>
                  <div>
                    <p className="text-[16px] font-semibold text-text">Урок пройден</p>
                    {course.data && (
                      <p className="mt-0.5 text-sm text-text2">
                        {course.data.lessons_completed} из {course.data.lessons_total}
                        {course.data.lessons_total > course.data.lessons_completed &&
                          ` · осталось ${plural(
                            course.data.lessons_total - course.data.lessons_completed,
                            'урок',
                            'урока',
                            'уроков',
                          )}`}
                      </p>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-3.5 rounded-[14px] border border-glass-border bg-tint p-4">
                  {rows.length > 0 && (
                    <>
                      <p className="text-xs font-bold uppercase tracking-[0.09em] text-text2">
                        Чтобы завершить урок
                      </p>
                      <ul className="flex flex-col gap-2.5">
                        {rows.map((row) => (
                          <GateRow key={row.label} done={row.done} label={row.label} />
                        ))}
                      </ul>
                    </>
                  )}
                  <button
                    type="button"
                    onClick={() => complete.mutate()}
                    disabled={complete.isPending}
                    className={cn(
                      'inline-flex h-[52px] items-center justify-center gap-2 rounded-xl bg-amber text-[15px] font-semibold text-on-amber',
                      !localReady && 'opacity-45',
                    )}
                  >
                    <Check className="h-[19px] w-[19px]" strokeWidth={2.2} />
                    Завершить урок
                  </button>
                  {!localReady && (
                    <p className="text-[13px] leading-[1.45] text-text2 [text-wrap:pretty]">
                      Условия выше ещё не выполнены — проверит сервер, он же назовёт
                      причину.
                    </p>
                  )}
                </div>
              )}

              <nav className="mt-5 flex flex-col gap-2.5">
                {data.next_lesson_id && (
                  <Link
                    to={data.next_locked ? '#' : `/learn/lessons/${data.next_lesson_id}`}
                    aria-disabled={data.next_locked}
                    onClick={(e) => data.next_locked && e.preventDefault()}
                    className={cn(
                      'flex min-h-[44px] items-center gap-2.5 rounded-xl px-3.5 py-3',
                      data.next_locked
                        ? 'cursor-not-allowed border border-dashed border-glass-border text-text2'
                        : 'bg-amber text-on-amber',
                    )}
                  >
                    <span className="min-w-0 flex-1 text-left">
                      <span className="block text-[11px] font-semibold uppercase tracking-[0.09em] opacity-70">
                        {data.next_locked
                          ? 'Откроется после этого урока'
                          : `Следующий · урок ${currentIndex + 2}`}
                      </span>
                      <span className="mt-0.5 block truncate text-[16px] font-semibold">
                        {nextMeta?.title ?? 'Следующий урок'}
                      </span>
                    </span>
                    <ArrowRight className="h-5 w-5 shrink-0" strokeWidth={2.2} />
                  </Link>
                )}

                {/* Последний урок: «Завершить курс» честен только когда курс
                    действительно закрыт — free-прогрессия могла оставить пропуски. */}
                {!data.next_lesson_id && data.completed && course.data?.completed && (
                  <div className="flex flex-col gap-3 rounded-[14px] border border-amber/35 bg-amber/[0.08] p-[18px] text-center">
                    <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-[14px] bg-amber text-on-amber">
                      <Trophy className="h-6 w-6" strokeWidth={1.9} />
                    </span>
                    <p className="font-display text-[18px] font-bold leading-[1.25] text-text">
                      Это последний урок курса
                    </p>
                    <p className="text-[15px] leading-[1.55] text-text2">
                      {`Все ${plural(course.data.lessons_total, 'урок', 'урока', 'уроков')} пройдены.`}
                      {course.data.certificate_enabled &&
                        ' Сертификат уже в вашем профиле.'}
                    </p>
                    <Link
                      to={courseHref}
                      className="inline-flex h-12 items-center justify-center gap-2 rounded-xl bg-amber text-[15px] font-semibold text-on-amber"
                    >
                      Завершить курс
                      <ArrowRight className="h-[18px] w-[18px]" strokeWidth={2.2} />
                    </Link>
                  </div>
                )}

                {!data.next_lesson_id && !(data.completed && course.data?.completed) && (
                  <Link
                    to={courseHref}
                    className="flex min-h-[44px] items-center gap-2.5 rounded-xl border border-glass-border px-3.5 py-3 text-text2"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block text-[11px] font-semibold uppercase tracking-[0.09em]">
                        К программе курса
                      </span>
                      <span className="mt-0.5 block truncate text-[16px] font-semibold text-text">
                        {course.data?.title ?? 'Курс'}
                      </span>
                    </span>
                    <ArrowRight className="h-5 w-5 shrink-0" strokeWidth={2.2} />
                  </Link>
                )}

                {data.prev_lesson_id && (
                  <Link
                    to={`/learn/lessons/${data.prev_lesson_id}`}
                    className="flex min-h-[44px] items-center gap-2.5 rounded-xl border border-glass-border px-3.5 py-3 text-text2"
                  >
                    <ArrowLeft className="h-5 w-5 shrink-0" strokeWidth={2.2} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[11px] font-semibold uppercase tracking-[0.09em]">
                        Предыдущий · урок {currentIndex}
                      </span>
                      <span className="mt-0.5 block truncate text-[16px] font-semibold text-text">
                        {prevMeta?.title ?? 'Предыдущий урок'}
                      </span>
                    </span>
                  </Link>
                )}
              </nav>
            </div>
          </>
        )}
        </article>
      </div>

      {data && (
        <aside className="hidden pt-14 lg:block">
          <LessonSections
            sections={sections}
            courseTitle={course.data?.title ?? 'Курс'}
            courseHref={courseHref}
            lessonsCompleted={course.data?.lessons_completed ?? 0}
            lessonsTotal={course.data?.lessons_total ?? 0}
            overdue={overdue}
          />
        </aside>
      )}
    </div>
  )
}
