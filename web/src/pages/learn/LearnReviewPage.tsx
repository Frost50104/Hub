import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ClipboardCheck, Clock, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useReviewQueue } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { extractErrorDetail } from '@/lib/errors'
import { learnApi, type QuizAttempt, type ReviewQueueItem } from '@/lib/learn'

/**
 * Очередь проверки открытых ответов (Ф3b, publisher/HR). Рендерится СНАПШОТ
 * попытки — именно то, что видел сотрудник; закрытые вопросы уже оценены
 * автоматически, HR выставляет баллы только открытым.
 */

function AttemptReview({
  item,
  onDone,
}: {
  item: ReviewQueueItem
  onDone: () => void
}) {
  const attempt = useQuery({
    queryKey: ['learn-review-attempt', item.attempt_id],
    queryFn: () => learnApi.quizAttempt(item.attempt_id),
  })
  const [scores, setScores] = useState<Record<string, number>>({})

  const review = useMutation({
    mutationFn: () => learnApi.reviewQuizAttempt(item.attempt_id, scores),
    meta: { suppressGlobalError: true },
    onSuccess: (a: QuizAttempt) => {
      toast.success(
        a.passed ? `Проверено: ${a.score_pct}% — сдан` : `Проверено: ${a.score_pct}% — не сдан`,
      )
      onDone()
    },
    onError: (e) =>
      toast.error('Не удалось сохранить проверку', { description: extractErrorDetail(e) }),
  })

  if (attempt.isLoading) return <SkeletonRows rows={4} />
  const data = attempt.data
  if (!data) return null

  const openQuestions = data.questions.filter(
    (q) =>
      q.qtype === 'open' &&
      typeof data.answers[q.id] === 'string' &&
      (data.answers[q.id] as string).trim(),
  )

  return (
    <div className="space-y-3">
      {data.questions.map((q) => {
        const answer = data.answers[q.id]
        const verdict = data.results?.[q.id]
        const isOpen = q.qtype === 'open'
        return (
          <div
            key={q.id}
            className="rounded-lg border border-glass-border bg-surface px-3 py-2.5 text-sm"
          >
            <p className="flex items-start gap-1.5 font-medium text-text">
              {verdict === true ? (
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green" />
              ) : verdict === false ? (
                <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red" />
              ) : (
                <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber" />
              )}
              {q.prompt}
            </p>
            {isOpen ? (
              <>
                <p className="mt-1.5 whitespace-pre-wrap rounded-md bg-glass px-2.5 py-1.5 text-text2">
                  {typeof answer === 'string' && answer.trim() ? answer : '— нет ответа —'}
                </p>
                {typeof answer === 'string' && answer.trim() && (
                  <div className="mt-1.5 flex items-center gap-2">
                    <span className="text-xs text-text3">Баллы (0–{q.points}):</span>
                    <Input
                      type="number"
                      min={0}
                      max={q.points}
                      step={0.5}
                      value={scores[q.id] ?? ''}
                      onChange={(e) =>
                        setScores((prev) => ({
                          ...prev,
                          [q.id]: Number(e.target.value),
                        }))
                      }
                      className="w-24"
                    />
                  </div>
                )}
              </>
            ) : (
              <p className="mt-1 text-xs text-text3">
                Оценён автоматически · {q.points} б.
              </p>
            )}
          </div>
        )
      })}
      <Button
        disabled={
          review.isPending ||
          openQuestions.some((q) => scores[q.id] === undefined || Number.isNaN(scores[q.id]))
        }
        onClick={() => review.mutate()}
      >
        <ClipboardCheck className="h-4 w-4" /> Завершить проверку
      </Button>
    </div>
  )
}

export function LearnReviewPage() {
  const isDesktop = useIsDesktop()
  const qc = useQueryClient()
  const queue = useReviewQueue()
  const [openId, setOpenId] = useState<string | null>(null)

  const items = queue.data ?? []

  return (
    <div className="mx-auto max-w-3xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Проверка тестов" />}
      <div className="space-y-4 p-4 lg:p-8">
        {isDesktop && (
          <h1 className="font-display text-2xl font-bold text-text">Проверка тестов</h1>
        )}

        {queue.isLoading && <SkeletonRows rows={4} />}
        {queue.isError && (
          <QueryError onRetry={() => void queue.refetch()} />
        )}

        {queue.data && items.length === 0 && (
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <ClipboardCheck className="mx-auto h-8 w-8 text-text3" />
            <p className="mt-3 text-sm text-text2">Очередь пуста — всё проверено.</p>
          </div>
        )}

        {items.map((item) => (
          <div
            key={item.attempt_id}
            className="rounded-xl border border-glass-border bg-glass p-4"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-text">{item.quiz_title}</p>
                <p className="text-xs text-text3">
                  {item.employee_name} · открытых ответов: {item.open_question_count}
                  {item.finished_at &&
                    ` · ${new Date(item.finished_at).toLocaleDateString('ru-RU', {
                      day: 'numeric',
                      month: 'long',
                    })}`}
                </p>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  setOpenId(openId === item.attempt_id ? null : item.attempt_id)
                }
              >
                {openId === item.attempt_id ? 'Свернуть' : 'Проверить'}
              </Button>
            </div>
            {openId === item.attempt_id && (
              <div className="mt-3 border-t border-glass-border pt-3">
                <AttemptReview
                  item={item}
                  onDone={() => {
                    setOpenId(null)
                    void qc.invalidateQueries({ queryKey: ['learn-review-queue'] })
                  }}
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
