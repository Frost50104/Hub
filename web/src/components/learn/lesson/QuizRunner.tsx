import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  CircleHelp,
  Clock,
  RotateCcw,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { useLessonQuiz } from '@/hooks/useLearn'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import {
  learnApi,
  type QuizAttempt,
  type QuizConsumer,
  type QuizSnapshotQuestion,
} from '@/lib/learn'

/**
 * Прохождение теста урока (Ф3b): вопрос-на-экран, автосохранение ответа
 * per-question (обрыв связи не теряет прогресс — попытка возобновляется),
 * сдача → результат или «на проверке» (открытые вопросы проверяет HR).
 * Правильные ответы приходят ТОЛЬКО после сдачи (show_correct_answers).
 */

function AnswerEditor({
  question,
  value,
  onChange,
}: {
  question: QuizSnapshotQuestion
  value: unknown
  onChange: (v: unknown) => void
}) {
  switch (question.qtype) {
    case 'single': {
      const options = question.options.options ?? []
      return (
        <div className="space-y-1">
          {options.map((option, i) => (
            <label
              key={i}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm',
                value === i
                  ? 'border-amber/60 bg-amber/10 text-text'
                  : 'border-glass-border bg-surface text-text2 hover:border-amber/40',
              )}
            >
              <input
                type="radio"
                checked={value === i}
                onChange={() => onChange(i)}
                className="accent-amber"
              />
              {option}
            </label>
          ))}
        </div>
      )
    }
    case 'multi': {
      const options = question.options.options ?? []
      const picked = new Set(Array.isArray(value) ? (value as number[]) : [])
      return (
        <div className="space-y-1">
          {options.map((option, i) => (
            <label
              key={i}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm',
                picked.has(i)
                  ? 'border-amber/60 bg-amber/10 text-text'
                  : 'border-glass-border bg-surface text-text2 hover:border-amber/40',
              )}
            >
              <input
                type="checkbox"
                checked={picked.has(i)}
                onChange={() => {
                  const next = new Set(picked)
                  if (next.has(i)) next.delete(i)
                  else next.add(i)
                  onChange([...next].sort((a, b) => a - b))
                }}
                className="accent-amber"
              />
              {option}
            </label>
          ))}
        </div>
      )
    }
    case 'match': {
      const left = question.options.left ?? []
      const right = question.options.right ?? []
      const picks = Array.isArray(value) ? (value as (number | null)[]) : []
      return (
        <div className="space-y-1.5">
          {left.map((item, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate rounded-md border border-glass-border bg-surface px-3 py-2 text-sm text-text">
                {item}
              </span>
              <Select
                value={picks[i] ?? ''}
                onChange={(e) => {
                  const next = left.map((_, j) => picks[j] ?? null)
                  next[i] = e.target.value === '' ? null : Number(e.target.value)
                  onChange(next)
                }}
                className="w-44"
              >
                <option value="">—</option>
                {right.map((r, j) => (
                  <option key={j} value={j}>
                    {r}
                  </option>
                ))}
              </Select>
            </div>
          ))}
        </div>
      )
    }
    case 'order': {
      const items = question.options.items ?? []
      const order = Array.isArray(value)
        ? (value as number[])
        : items.map((_, i) => i)
      const move = (from: number, delta: number) => {
        const to = from + delta
        if (to < 0 || to >= order.length) return
        const next = [...order]
        const tmp = next[from]!
        next[from] = next[to]!
        next[to] = tmp
        onChange(next)
      }
      return (
        <div className="space-y-1">
          {order.map((itemIdx, pos) => (
            <div
              key={itemIdx}
              className="flex items-center gap-2 rounded-md border border-glass-border bg-surface px-3 py-2 text-sm text-text"
            >
              <span className="w-5 text-center text-xs text-text3">{pos + 1}</span>
              <span className="min-w-0 flex-1 truncate">{items[itemIdx]}</span>
              <button
                type="button"
                aria-label="Выше"
                disabled={pos === 0}
                onClick={() => move(pos, -1)}
                className="rounded p-1 text-text3 hover:text-text disabled:opacity-30"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
              <button
                type="button"
                aria-label="Ниже"
                disabled={pos === order.length - 1}
                onClick={() => move(pos, 1)}
                className="rounded p-1 text-text3 hover:text-text disabled:opacity-30"
              >
                <ArrowDown className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )
    }
    case 'open':
      return (
        <textarea
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
          rows={4}
          placeholder="Ваш ответ…"
          className="flex w-full rounded-lg border border-glass-border bg-surface px-3 py-2 text-sm text-text placeholder:text-text3 focus-visible:border-amber focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber"
        />
      )
    default:
      return null
  }
}

function correctAnswerText(
  question: QuizSnapshotQuestion,
  answer: Record<string, unknown>,
): string {
  if (question.qtype === 'single' || question.qtype === 'multi') {
    const options = question.options.options ?? []
    const correct = (answer.correct as number[]) ?? []
    return correct.map((i) => options[i]).join(', ')
  }
  if (question.qtype === 'match') {
    const left = question.options.left ?? []
    const right = question.options.right ?? []
    const pairs = (answer.pairs as [number, number][]) ?? []
    return pairs.map(([li, ri]) => `${left[li]} → ${right[ri]}`).join('; ')
  }
  if (question.qtype === 'order') {
    const items = question.options.items ?? []
    const order = (answer.order as number[]) ?? []
    return order.map((i) => items[i]).join(' → ')
  }
  return ''
}

export function AttemptView({
  attempt,
  onFinished,
}: {
  attempt: QuizAttempt
  onFinished: (a: QuizAttempt) => void
}) {
  const [answers, setAnswers] = useState<Record<string, unknown>>(attempt.answers)
  const [index, setIndex] = useState(0)
  const questions = attempt.questions
  const question = questions[index]

  const save = useMutation({
    mutationFn: ({ qid, value }: { qid: string; value: unknown }) =>
      learnApi.saveQuizAnswer(attempt.id, qid, value),
    meta: { suppressGlobalError: true },
    onError: (e) =>
      toast.error('Ответ не сохранился', { description: extractErrorDetail(e) }),
  })
  const submit = useMutation({
    mutationFn: () => learnApi.submitQuizAttempt(attempt.id),
    meta: { suppressGlobalError: true },
    onSuccess: onFinished,
    onError: (e) =>
      toast.error('Не удалось сдать тест', { description: extractErrorDetail(e) }),
  })

  if (!question) return null

  const setAnswer = (value: unknown) => {
    setAnswers((prev) => ({ ...prev, [question.id]: value }))
    save.mutate({ qid: question.id, value })
  }

  const answeredCount = questions.filter((q) => answers[q.id] !== undefined).length

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-text3">
        <span>
          Вопрос {index + 1} из {questions.length}
        </span>
        <span>{answeredCount}/{questions.length} отвечено</span>
      </div>
      <span className="block h-1 overflow-hidden rounded-full bg-surface">
        <span
          className="block h-full rounded-full bg-amber transition-all"
          style={{ width: `${((index + 1) / questions.length) * 100}%` }}
        />
      </span>

      <p className="text-sm font-medium text-text">{question.prompt}</p>
      {question.media_url && (
        <img
          src={question.media_url}
          alt=""
          className="max-h-64 rounded-lg border border-glass-border"
        />
      )}
      <AnswerEditor
        question={question}
        value={answers[question.id]}
        onChange={setAnswer}
      />

      <div className="flex items-center justify-between pt-1">
        <Button
          variant="ghost"
          size="sm"
          disabled={index === 0}
          onClick={() => setIndex((i) => i - 1)}
        >
          <ArrowLeft className="h-4 w-4" /> Назад
        </Button>
        {index < questions.length - 1 ? (
          <Button size="sm" onClick={() => setIndex((i) => i + 1)}>
            Далее <ArrowRight className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            size="sm"
            disabled={submit.isPending}
            onClick={() => submit.mutate()}
          >
            <Check className="h-4 w-4" /> Сдать тест
          </Button>
        )}
      </div>
    </div>
  )
}

export function ResultView({
  attempt,
  quiz,
  onRetry,
  canRetry,
}: {
  attempt: QuizAttempt
  quiz: QuizConsumer
  onRetry: () => void
  canRetry: boolean
}) {
  const [showBreakdown, setShowBreakdown] = useState(false)
  if (attempt.needs_review) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-amber/40 bg-amber/5 px-3 py-2.5 text-sm text-text2">
        <Clock className="h-4 w-4 shrink-0 text-amber" />
        Тест сдан и ждёт проверки открытых ответов — мы пришлём уведомление.
      </div>
    )
  }
  return (
    <div className="space-y-2">
      <div
        className={cn(
          'flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm',
          attempt.passed
            ? 'border-green/50 bg-green/10 text-text'
            : 'border-red/50 bg-red/10 text-text',
        )}
      >
        {attempt.passed ? (
          <Check className="h-4 w-4 shrink-0 text-green" />
        ) : (
          <X className="h-4 w-4 shrink-0 text-red" />
        )}
        {attempt.passed
          ? `Тест сдан: ${attempt.score_pct}% (порог ${quiz.pass_score_pct}%)`
          : `Не сдан: ${attempt.score_pct}% при пороге ${quiz.pass_score_pct}%`}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {attempt.results && quiz.show_correct_answers && (
          <Button variant="ghost" size="sm" onClick={() => setShowBreakdown((v) => !v)}>
            {showBreakdown ? 'Скрыть разбор' : 'Показать разбор'}
          </Button>
        )}
        {!attempt.passed && canRetry && (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            <RotateCcw className="h-4 w-4" /> Попробовать ещё раз
          </Button>
        )}
      </div>
      {showBreakdown && attempt.results && (
        <div className="space-y-2">
          {attempt.questions.map((q) => {
            const verdict = attempt.results?.[q.id]
            const correct = attempt.correct_answers?.[q.id]
            return (
              <div
                key={q.id}
                className="rounded-lg border border-glass-border bg-surface px-3 py-2 text-sm"
              >
                <p className="flex items-center gap-1.5 text-text">
                  {verdict === true ? (
                    <Check className="h-3.5 w-3.5 shrink-0 text-green" />
                  ) : verdict === false ? (
                    <X className="h-3.5 w-3.5 shrink-0 text-red" />
                  ) : (
                    <Clock className="h-3.5 w-3.5 shrink-0 text-amber" />
                  )}
                  {q.prompt}
                </p>
                {verdict === false && correct && (
                  <p className="mt-1 text-xs text-text3">
                    Правильно: {correctAnswerText(q, correct)}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function QuizRunner({ lessonId }: { lessonId: string }) {
  const qc = useQueryClient()
  const quizQuery = useLessonQuiz(lessonId)
  const [attempt, setAttempt] = useState<QuizAttempt | null>(null)
  const [finished, setFinished] = useState<QuizAttempt | null>(null)

  const start = useMutation({
    mutationFn: (quizId: string) => learnApi.startQuizAttempt(quizId),
    meta: { suppressGlobalError: true },
    onSuccess: (a) => {
      setFinished(null)
      setAttempt(a)
    },
    onError: (e) =>
      toast.error('Не удалось начать тест', { description: extractErrorDetail(e) }),
  })

  const quiz = quizQuery.data
  if (!quiz) return null

  const onFinished = (a: QuizAttempt) => {
    setAttempt(null)
    setFinished(a)
    void qc.invalidateQueries({ queryKey: ['learn-lesson-quiz', lessonId] })
    void qc.invalidateQueries({ queryKey: ['learn-lesson', lessonId] })
    void qc.invalidateQueries({ queryKey: ['learn-course'] })
  }

  const attemptsLabel =
    quiz.attempts_limit !== null
      ? `попыток: ${quiz.attempts_used}/${quiz.attempts_limit}`
      : `попыток использовано: ${quiz.attempts_used}`

  return (
    <div className="rounded-xl border border-glass-border bg-glass p-4">
      <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-text2">
        <CircleHelp className="h-3.5 w-3.5 text-amber" />
        Тест урока
        {quiz.is_required && (
          <span className="rounded bg-amber/15 px-1.5 py-0.5 text-[10px] normal-case text-amber">
            открывает следующий урок
          </span>
        )}
      </p>
      <p className="text-sm font-medium text-text">{quiz.title}</p>
      {quiz.description && <p className="mt-0.5 text-sm text-text2">{quiz.description}</p>}
      <p className="mt-0.5 text-xs text-text3">
        {quiz.question_count} вопросов · порог {quiz.pass_score_pct}% · {attemptsLabel}
      </p>

      <div className="mt-3">
        {attempt ? (
          <AttemptView attempt={attempt} onFinished={onFinished} />
        ) : finished ? (
          <ResultView
            attempt={finished}
            quiz={quiz}
            canRetry={quiz.attempts_limit === null || quiz.attempts_used < quiz.attempts_limit}
            onRetry={() => start.mutate(quiz.id)}
          />
        ) : quiz.pending_review ? (
          <div className="flex items-center gap-2 rounded-lg border border-amber/40 bg-amber/5 px-3 py-2.5 text-sm text-text2">
            <Clock className="h-4 w-4 shrink-0 text-amber" />
            Попытка на проверке — дождитесь результата.
          </div>
        ) : quiz.passed ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-green/50 bg-green/10 px-3 py-2 text-sm text-text">
              <Check className="h-4 w-4 text-green" /> Сдан на {quiz.best_score_pct}%
            </span>
            {quiz.can_start && (
              <Button
                variant="ghost"
                size="sm"
                disabled={start.isPending}
                onClick={() => start.mutate(quiz.id)}
              >
                <RotateCcw className="h-4 w-4" /> Пройти снова
              </Button>
            )}
          </div>
        ) : quiz.can_start ? (
          <Button
            size="sm"
            disabled={start.isPending}
            onClick={() => start.mutate(quiz.id)}
          >
            {quiz.active_attempt_id ? 'Продолжить тест' : 'Начать тест'}
          </Button>
        ) : (
          <div className="flex items-center gap-2 rounded-lg border border-red/40 bg-red/5 px-3 py-2.5 text-sm text-text2">
            <X className="h-4 w-4 shrink-0 text-red" />
            Лимит попыток исчерпан — обратитесь к руководителю.
          </div>
        )}
      </div>
    </div>
  )
}
