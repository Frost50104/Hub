import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  Check,
  ChevronLeft,
  CircleHelp,
  Clock,
  RotateCcw,
  X,
} from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { useLessonQuiz } from '@/hooks/useLearn'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import {
  learnApi,
  type QuizAttempt,
  type QuizConsumer,
  type QuizSnapshotQuestion,
} from '@/lib/learn'
import { plural } from '@/lib/typography'

import { QuizAnswer } from './QuizAnswer'

/**
 * Прохождение теста урока (Ф3b): вопрос-на-экран, автосохранение ответа
 * per-question (обрыв связи не теряет прогресс — попытка возобновляется),
 * сдача → результат или «на проверке» (открытые вопросы проверяет HR).
 * Правильные ответы приходят ТОЛЬКО после сдачи (show_correct_answers).
 *
 * Попытка идёт полноэкранно поверх урока: тест — отдельная работа, а не
 * блок в тексте, и нижняя кнопка обязана стоять над таб-баром.
 */

const HINT: Record<string, string> = {
  single: 'Один верный ответ',
  multi: 'Несколько верных ответов',
  match: 'Выберите термин, затем его определение',
  order: 'Меняйте порядок стрелками',
  open: 'Свободный ответ · проверит человек, баллы придут после проверки',
}

function isAnswered(question: QuizSnapshotQuestion, value: unknown): boolean {
  switch (question.qtype) {
    case 'single':
      return typeof value === 'number'
    case 'multi':
      return Array.isArray(value) && value.length > 0
    case 'match':
      return (
        Array.isArray(value) &&
        value.length === (question.options.left ?? []).length &&
        value.every((v) => v !== null && v !== undefined)
      )
    case 'order':
      return true // порядок всегда валиден: он задан с самого начала
    case 'open':
      return typeof value === 'string' && value.trim().length > 0
    default:
      return false
  }
}

/**
 * Оболочка полноэкранной попытки: шапка с выходом, тело со скроллом и
 * закреплённый низ. z-40 — выше таб-бара (z-30), иначе кнопка «Далее»
 * оказалась бы под ним; отступ снизу учитывает safe-area.
 */
function QuizScreen({
  eyebrow,
  title,
  trailing,
  onExit,
  progress,
  children,
  footer,
}: {
  eyebrow: string
  title: string
  trailing?: ReactNode
  onExit: () => void
  progress?: ReactNode
  children: ReactNode
  footer: ReactNode
}) {
  // Пока попытка открыта, страница урока под ней скроллиться не должна:
  // на телефоне это выглядит как «экран поехал сам по себе».
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-bg">
      <div className="shrink-0 border-b border-hair px-5 pb-3 pt-11">
        <div className="mx-auto flex max-w-[680px] items-center gap-2.5">
          <button
            type="button"
            onClick={onExit}
            aria-label="Выйти из теста"
            className="-ml-2.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-text2 hover:text-text"
          >
            <X className="h-[22px] w-[22px]" />
          </button>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[11px] font-semibold uppercase tracking-[0.1em] text-text2">
              {eyebrow}
            </p>
            <p className="truncate text-sm font-medium text-text">{title}</p>
          </div>
          {trailing}
        </div>
        {progress && <div className="mx-auto mt-3 max-w-[680px]">{progress}</div>}
      </div>

      <div className="flex-1 overflow-y-auto overscroll-contain">
        <div className="mx-auto max-w-[680px] px-5 pb-7 pt-6">{children}</div>
      </div>

      <div
        className="shrink-0 border-t border-hair px-5 pb-4 pt-3"
        style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 1rem)' }}
      >
        <div className="mx-auto max-w-[680px]">{footer}</div>
      </div>
    </div>
  )
}

export function AttemptView({
  attempt,
  quiz,
  onFinished,
  onExit,
}: {
  attempt: QuizAttempt
  quiz: QuizConsumer
  onFinished: (a: QuizAttempt) => void
  onExit: () => void
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

  const answered = isAnswered(question, answers[question.id])
  const isLast = index === questions.length - 1
  const isOpen = question.qtype === 'open'

  return (
    <QuizScreen
      eyebrow={`Тест · ${quiz.title}`}
      title={`Вопрос ${index + 1} из ${questions.length}`}
      trailing={
        <span className="shrink-0 text-xs font-medium text-text2">
          проходной {quiz.pass_score_pct}%
        </span>
      }
      onExit={onExit}
      progress={
        <div className="flex gap-[3px]">
          {questions.map((q, i) => (
            <span
              key={q.id}
              className={cn(
                'block h-[3px] flex-1 rounded-full',
                i < index ? 'bg-green' : i === index ? 'bg-amber' : 'bg-surface',
              )}
            />
          ))}
        </div>
      }
      footer={
        <div className="flex flex-col gap-2">
          <div className="flex gap-2">
            <button
              type="button"
              disabled={index === 0}
              onClick={() => setIndex((i) => i - 1)}
              className="inline-flex h-[52px] items-center justify-center gap-2 rounded-xl border border-glass-border px-4 text-[15px] font-semibold text-text disabled:opacity-45"
            >
              <ChevronLeft className="h-[17px] w-[17px]" strokeWidth={2.2} /> Назад
            </button>
            <button
              type="button"
              disabled={submit.isPending}
              onClick={() => (isLast ? submit.mutate() : setIndex((i) => i + 1))}
              className={cn(
                'inline-flex h-[52px] flex-1 items-center justify-center gap-2.5 rounded-xl bg-amber text-[16px] font-semibold text-on-amber',
                !answered && 'opacity-45',
              )}
            >
              {isLast ? (isOpen ? 'Отправить на проверку' : 'Сдать тест') : 'Далее'}
              <ArrowRight className="h-[19px] w-[19px]" strokeWidth={2.2} />
            </button>
          </div>
          <p className="text-center text-[13px] leading-[1.45] text-text2">
            {answered
              ? 'Ответ сохраняется сразу — при обрыве связи попытка продолжится с этого вопроса.'
              : 'Ответьте на вопрос, чтобы продолжить.'}
          </p>
        </div>
      }
    >
      <p className="mb-2 text-xs font-bold uppercase tracking-[0.09em] text-text2">
        {HINT[question.qtype] ?? ''}
      </p>
      <h2 className="mb-5 font-display text-[21px] font-bold leading-[1.3] tracking-[0.01em] text-text [text-wrap:pretty] lg:text-[26px] lg:leading-[1.28]">
        {question.prompt}
      </h2>
      {question.media_url && (
        <img
          src={question.media_url}
          alt=""
          className="mb-5 block h-[180px] w-full rounded-xl object-cover lg:h-[260px]"
        />
      )}
      <QuizAnswer question={question} value={answers[question.id]} onChange={setAnswer} />
    </QuizScreen>
  )
}

export function ResultView({
  attempt,
  quiz,
  onRetry,
  onExit,
  canRetry,
}: {
  attempt: QuizAttempt
  quiz: QuizConsumer
  onRetry: () => void
  onExit: () => void
  canRetry: boolean
}) {
  const [showBreakdown, setShowBreakdown] = useState(false)

  const attemptsLabel =
    quiz.attempts_limit !== null
      ? `попыток: ${quiz.attempts_used}/${quiz.attempts_limit}`
      : `попыток использовано: ${quiz.attempts_used}`

  // needs_review — не третий вариант результата, а отдельный экран: сервер не
  // присылает ни балла, ни разбора, и кольцо с «—» обещало бы число, которого
  // не существует.
  if (attempt.needs_review) {
    return (
      <QuizScreen
        eyebrow={`Тест · ${quiz.title}`}
        title="Отправлено на проверку"
        onExit={onExit}
        footer={
          <button
            type="button"
            onClick={onExit}
            className="inline-flex h-[52px] w-full items-center justify-center rounded-xl bg-amber text-[16px] font-semibold text-on-amber"
          >
            Вернуться к уроку
          </button>
        }
      >
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-amber text-on-amber">
            <Clock className="h-7 w-7" strokeWidth={1.9} />
          </span>
          <h2 className="font-display text-xl font-bold leading-[1.25] text-text lg:text-[22px]">
            Тест сдан и ждёт проверки
          </h2>
          <p className="max-w-[420px] text-[15px] leading-[1.55] text-text2 [text-wrap:pretty]">
            Открытые ответы проверяет человек — мы пришлём уведомление, когда балл
            будет готов.
          </p>
        </div>
      </QuizScreen>
    )
  }

  const passed = attempt.passed === true
  const correctCount = attempt.results
    ? Object.values(attempt.results).filter((v) => v === true).length
    : 0

  return (
    <QuizScreen
      eyebrow={`Тест · ${quiz.title}`}
      title={`Тест завершён · ${plural(attempt.questions.length, 'вопрос', 'вопроса', 'вопросов')}`}
      onExit={onExit}
      footer={
        <div className="flex flex-col gap-2">
          {!passed && canRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex h-[52px] w-full items-center justify-center gap-2.5 rounded-xl bg-amber text-[16px] font-semibold text-on-amber"
            >
              <RotateCcw className="h-[19px] w-[19px]" /> Попробовать ещё раз
            </button>
          ) : (
            <button
              type="button"
              onClick={onExit}
              className="inline-flex h-[52px] w-full items-center justify-center rounded-xl bg-amber text-[16px] font-semibold text-on-amber"
            >
              Вернуться к уроку
            </button>
          )}
          <p className="text-center text-[13px] text-text2">{attemptsLabel}</p>
        </div>
      }
    >
      <div className="flex flex-col items-center gap-5 text-center">
        {/* Кольцо 140px: процент набран Unbounded 34/700 — на 44px «100%»
            упиралось в обводку. */}
        <span
          className={cn(
            'flex h-[140px] w-[140px] items-center justify-center rounded-full border-[6px]',
            passed ? 'border-green' : 'border-red',
          )}
        >
          <span className="font-display text-[34px] font-bold tracking-[-0.01em] tabular-nums text-text">
            {attempt.score_pct ?? 0}%
          </span>
        </span>

        <div className="flex flex-col gap-1.5">
          <h2 className="font-display text-[22px] font-bold leading-[1.25] text-text lg:text-[28px]">
            {passed ? 'Тест сдан' : 'Не сдан'}
          </h2>
          <p className="text-[15px] text-text2">
            проходной балл {quiz.pass_score_pct}% · верно {correctCount} из{' '}
            {attempt.questions.length}
          </p>
        </div>

        {attempt.results && quiz.show_correct_answers && (
          <button
            type="button"
            onClick={() => setShowBreakdown((v) => !v)}
            className="inline-flex min-h-[44px] items-center rounded-xl border border-glass-border px-4 text-[15px] font-semibold text-text"
          >
            {showBreakdown ? 'Скрыть разбор' : 'Показать разбор'}
          </button>
        )}
      </div>

      {showBreakdown && attempt.results && (
        <div className="mt-6 flex flex-col gap-2">
          {attempt.questions.map((q) => {
            const verdict = attempt.results?.[q.id]
            const correct = attempt.correct_answers?.[q.id]
            return (
              <div
                key={q.id}
                className={cn(
                  'flex min-h-[52px] items-start gap-3 rounded-xl border px-3.5 py-3',
                  verdict === false
                    ? 'border-red/40 bg-red/[0.05]'
                    : verdict === null
                      ? 'border-glass-border bg-tint'
                      : 'border-hair',
                )}
              >
                <span
                  className={cn(
                    'mt-0.5 flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full',
                    verdict === true
                      ? 'bg-green-deep text-bg'
                      : verdict === false
                        ? 'bg-red/[0.16] text-red'
                        : 'bg-surface text-text2',
                  )}
                >
                  {verdict === true ? (
                    <Check className="h-3.5 w-3.5" strokeWidth={3} />
                  ) : verdict === false ? (
                    <X className="h-3.5 w-3.5" strokeWidth={3} />
                  ) : (
                    <Clock className="h-3.5 w-3.5" />
                  )}
                </span>
                <span className="min-w-0 flex-1 text-left">
                  <span className="block text-[15px] font-medium leading-[1.4] text-text">
                    {q.prompt}
                  </span>
                  {/* Правильный ответ подписывается только у неверных. */}
                  <span
                    className={cn(
                      'mt-0.5 block text-[13px] leading-[1.4]',
                      verdict === false ? 'text-text' : 'text-text2',
                    )}
                  >
                    {verdict === true
                      ? 'Верно'
                      : verdict === false
                        ? correct
                          ? `Правильно: ${correctAnswerText(q, correct)}`
                          : 'Неверно'
                        : 'Открытый ответ · проверяет человек'}
                  </span>
                </span>
              </div>
            )
          })}
        </div>
      )}
    </QuizScreen>
  )
}

function correctAnswerText(
  question: QuizSnapshotQuestion,
  correct: Record<string, unknown>,
): string {
  const options = question.options.options ?? []
  const value = correct.correct
  if (typeof value === 'number') return options[value] ?? String(value)
  if (Array.isArray(value)) {
    return value.map((i) => (typeof i === 'number' ? (options[i] ?? i) : i)).join(', ')
  }
  if (typeof value === 'string') return value
  return '—'
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

  if (attempt) {
    return (
      <AttemptView
        attempt={attempt}
        quiz={quiz}
        onFinished={onFinished}
        onExit={() => setAttempt(null)}
      />
    )
  }

  if (finished) {
    return (
      <ResultView
        attempt={finished}
        quiz={quiz}
        canRetry={quiz.attempts_limit === null || quiz.attempts_used < quiz.attempts_limit}
        onRetry={() => start.mutate(quiz.id)}
        onExit={() => setFinished(null)}
      />
    )
  }

  return (
    <div className="my-7 rounded-[14px] border border-glass-border bg-tint p-4 lg:my-8">
      <p className="mb-2 flex flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-[0.09em] text-text2">
        <span className="inline-flex items-center gap-1.5">
          <CircleHelp className="h-3.5 w-3.5" />
          Тест урока
        </span>
        {quiz.is_required && (
          <span className="rounded-md bg-surface px-[7px] py-[3px] text-[11px] font-medium normal-case tracking-normal text-text2">
            открывает следующий урок
          </span>
        )}
      </p>
      <p className="text-[18px] font-semibold leading-[1.4] text-text lg:text-[19px]">
        {quiz.title}
      </p>
      {quiz.description && (
        <p className="mt-1 text-[15px] leading-[1.5] text-text2">{quiz.description}</p>
      )}
      <p className="mt-1.5 text-[13px] text-text2">
        {plural(quiz.question_count, 'вопрос', 'вопроса', 'вопросов')} · порог{' '}
        {quiz.pass_score_pct}% · {attemptsLabel}
      </p>

      <div className="mt-4">
        {quiz.pending_review ? (
          <p className="flex items-center gap-2 rounded-xl border border-amber/40 bg-amber/5 px-3.5 py-3 text-[15px] text-text2">
            <Clock className="h-4 w-4 shrink-0 text-amber" />
            Попытка на проверке — дождитесь результата.
          </p>
        ) : quiz.passed ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-xl border border-green/40 bg-green/[0.09] px-3.5 py-2.5 text-[15px] text-text">
              <Check className="h-4 w-4 text-green" /> Сдан на {quiz.best_score_pct}%
            </span>
            {quiz.can_start && (
              <Button variant="ghost" disabled={start.isPending} onClick={() => start.mutate(quiz.id)}>
                <RotateCcw className="h-4 w-4" /> Пройти снова
              </Button>
            )}
          </div>
        ) : quiz.can_start ? (
          <button
            type="button"
            disabled={start.isPending}
            onClick={() => start.mutate(quiz.id)}
            className="inline-flex h-[52px] w-full items-center justify-center gap-2 rounded-xl bg-amber text-[16px] font-semibold text-on-amber sm:w-auto sm:px-6"
          >
            {quiz.active_attempt_id ? 'Продолжить тест' : 'Начать тест'}
            <ArrowRight className="h-[19px] w-[19px]" strokeWidth={2.2} />
          </button>
        ) : (
          <p className="flex items-center gap-2 rounded-xl border border-red/40 bg-red/5 px-3.5 py-3 text-[15px] text-text2">
            <X className="h-4 w-4 shrink-0 text-red" />
            Лимит попыток исчерпан — обратитесь к руководителю.
          </p>
        )}
      </div>
    </div>
  )
}
