import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ExternalLink,
  FileText,
  Lock,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { LessonRenderer } from '@/components/learn/lesson/LessonRenderer'
import { QuizRunner } from '@/components/learn/lesson/QuizRunner'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useLesson } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { extractErrorDetail } from '@/lib/errors'
import { learnApi, type LessonContent } from '@/lib/learn'

/**
 * Прохождение урока (Ф3a). «Завершить урок» — явное действие; сервер
 * проверяет предусловия (gate-вопросы + досмотр видео ≥90%) и вернёт 409
 * с человекочитаемой причиной — локальный чек-лист лишь подсказывает.
 */

const WATCH_THRESHOLD = 0.9

function isLockedError(err: unknown): boolean {
  return (err as { response?: { status?: number } }).response?.status === 403
}

function GateChecklist({
  lesson,
  answeredGates,
  videoCoverage,
}: {
  lesson: LessonContent
  answeredGates: Set<string>
  videoCoverage: Record<string, number>
}) {
  if (!lesson.gate_blocks.length && !lesson.required_videos.length) return null
  const gatesDone = lesson.gate_blocks.filter((b) => answeredGates.has(b)).length
  const videosDone = lesson.required_videos.filter(
    (m) => (videoCoverage[m] ?? 0) >= WATCH_THRESHOLD,
  ).length
  const rows: { label: string; done: boolean }[] = []
  if (lesson.gate_blocks.length) {
    rows.push({
      label:
        lesson.gate_blocks.length === 1
          ? 'Ответить на контрольный вопрос'
          : `Ответить на контрольные вопросы (${gatesDone}/${lesson.gate_blocks.length})`,
      done: gatesDone >= lesson.gate_blocks.length,
    })
  }
  if (lesson.required_videos.length) {
    rows.push({
      label:
        lesson.required_videos.length === 1
          ? 'Досмотреть видео (минимум 90%)'
          : `Досмотреть видео (${videosDone}/${lesson.required_videos.length})`,
      done: videosDone >= lesson.required_videos.length,
    })
  }
  return (
    <ul className="space-y-1 text-sm">
      {rows.map((row, i) => (
        <li key={i} className="flex items-center gap-2">
          <span
            className={
              row.done
                ? 'flex h-4 w-4 items-center justify-center rounded-full bg-green/20 text-green'
                : 'h-4 w-4 rounded-full border border-glass-border'
            }
          >
            {row.done && <Check className="h-3 w-3" />}
          </span>
          <span className={row.done ? 'text-text3 line-through' : 'text-text2'}>
            {row.label}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function LearnLessonPage() {
  const { lessonId } = useParams<{ lessonId: string }>()
  const isDesktop = useIsDesktop()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const lesson = useLesson(lessonId)

  const [answeredExtra, setAnsweredExtra] = useState<Set<string>>(new Set())
  const [liveCoverage, setLiveCoverage] = useState<Record<string, number>>({})

  const data = lesson.data

  // Начальное состояние гейтов — из block_state сервера; live-ответы поверх.
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
    mutationFn: () => learnApi.completeLesson(lessonId!),
    meta: { suppressGlobalError: true },
    onSuccess: (fresh) => {
      qc.setQueryData(['learn-lesson', lessonId], fresh)
      void qc.invalidateQueries({ queryKey: ['learn-course'] })
      void qc.invalidateQueries({ queryKey: ['learn-courses'] })
      toast.success('Урок пройден')
    },
    onError: (err) => {
      toast.error('Урок ещё не завершён', { description: extractErrorDetail(err) })
    },
  })

  const localReady =
    !data ||
    (data.gate_blocks.every((b) => answeredGates.has(b)) &&
      data.required_videos.every((m) => (videoCoverage[m] ?? 0) >= WATCH_THRESHOLD))

  return (
    <div className="mx-auto max-w-3xl">
      {!isDesktop && (
        <MobilePageHeader eyebrow="Урок" title={data?.title ?? 'Урок'} />
      )}
      <div className="space-y-4 p-4 lg:p-8">
        <Link
          to={data ? `/learn/courses/${data.course_id}` : '/learn/courses'}
          className="inline-flex items-center gap-1.5 text-sm text-text3 hover:text-text"
        >
          <ArrowLeft className="h-4 w-4" /> К курсу
        </Link>

        {lesson.isLoading && <SkeletonRows rows={6} />}
        {lesson.isError &&
          (isLockedError(lesson.error) ? (
            <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
              <Lock className="mx-auto h-8 w-8 text-text3" />
              <p className="mt-3 text-sm text-text2">
                Этот урок откроется после завершения предыдущих.
              </p>
            </div>
          ) : (
            <QueryError onRetry={() => void lesson.refetch()} />
          ))}

        {data && (
          <>
            {isDesktop && (
              <h1 className="font-display text-2xl font-bold text-text">{data.title}</h1>
            )}

            {data.content_format === 'pdf' && data.pdf_url && (
              <div className="space-y-2">
                <iframe
                  src={data.pdf_url}
                  title={data.title}
                  className="h-[70vh] w-full rounded-lg border border-glass-border bg-white"
                />
                {!data.forbid_download && (
                  <a
                    href={data.pdf_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-sm text-amber hover:opacity-80"
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

            <div className="rounded-xl border border-glass-border bg-glass p-4">
              {data.completed ? (
                <p className="inline-flex items-center gap-2 text-sm text-green">
                  <CheckCircle2 className="h-5 w-5" /> Урок пройден
                </p>
              ) : (
                <div className="space-y-3">
                  <GateChecklist
                    lesson={data}
                    answeredGates={answeredGates}
                    videoCoverage={videoCoverage}
                  />
                  <Button
                    onClick={() => complete.mutate()}
                    disabled={complete.isPending}
                    className={!localReady ? 'opacity-60' : undefined}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Завершить урок
                  </Button>
                </div>
              )}

              <div className="mt-3 flex items-center justify-between border-t border-glass-border pt-3">
                {data.prev_lesson_id ? (
                  <Button
                    variant="ghost"
                    onClick={() => navigate(`/learn/lessons/${data.prev_lesson_id}`)}
                  >
                    <ArrowLeft className="h-4 w-4" /> Предыдущий
                  </Button>
                ) : (
                  <span />
                )}
                {data.next_lesson_id && (
                  <Button
                    variant={data.completed ? 'default' : 'ghost'}
                    disabled={data.next_locked}
                    title={data.next_locked ? 'Сначала завершите этот урок' : undefined}
                    onClick={() => navigate(`/learn/lessons/${data.next_lesson_id}`)}
                  >
                    Следующий <ArrowRight className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
