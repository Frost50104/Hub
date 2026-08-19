import { useMutation } from '@tanstack/react-query'
import { Check, CircleHelp, X } from 'lucide-react'
import { useState } from 'react'

import { cn } from '@/lib/cn'
import { learnApi } from '@/lib/learn'

/** Буквы вариантов — как в макете: кружок с буквой, а не голая точка. */
const LETTERS = ['А', 'Б', 'В', 'Г', 'Д', 'Е', 'Ж', 'З', 'И', 'К']

/**
 * Контрольный вопрос внутри урока (Ф3a). Правильный ответ знает ТОЛЬКО
 * сервер (attrs.correct вырезан из consumer-контента) — проверка через
 * POST /blocks/{id}/answer. Неверный ответ можно переиграть; gate-вопросы
 * обязаны быть отвечены до «Завершить урок».
 */
export function CheckQuestion({
  lessonId,
  blockId,
  question,
  options,
  gateNext = false,
  initialAnswer,
  lessonCompleted = false,
  onAnswered,
}: {
  lessonId: string
  blockId: string
  question: string
  options: string[]
  gateNext?: boolean
  initialAnswer?: { answer: number; correct: boolean }
  /** Урок завершён: block_state хранит ПОСЛЕДНИЙ ответ (мог быть неверным
   * до верного) — красное «Неверно» при повторном просмотре сбивает с толку. */
  lessonCompleted?: boolean
  onAnswered?: (blockId: string, correct: boolean) => void
}) {
  const [selected, setSelected] = useState<number | null>(initialAnswer?.answer ?? null)
  const [result, setResult] = useState<{ answer: number; correct: boolean } | null>(
    initialAnswer ?? null,
  )

  const submit = useMutation({
    mutationFn: (answer: number) => learnApi.answerBlock(lessonId, blockId, answer),
    onSuccess: (data, answer) => {
      setResult({ answer, correct: data.correct })
      onAnswered?.(blockId, data.correct)
    },
  })

  const answered = result !== null
  const solvedCorrectly = result?.correct === true

  return (
    <div
      className={cn(
        'my-7 rounded-[14px] border p-4 lg:my-8 lg:p-5',
        solvedCorrectly
          ? 'border-green/40 bg-green/[0.06]'
          : answered
            ? 'border-red/40 bg-red/[0.06]'
            : 'border-amber/40 bg-amber/5',
      )}
    >
      <p className="mb-3 flex flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-[0.09em] text-text2">
        <span className="inline-flex items-center gap-1.5">
          <CircleHelp className="h-3.5 w-3.5" />
          Проверьте себя
        </span>
        {gateNext && !solvedCorrectly && (
          <span className="rounded-md bg-surface px-[7px] py-[3px] text-[11px] font-medium normal-case tracking-normal text-text2">
            нужен ответ, чтобы завершить урок
          </span>
        )}
      </p>
      <p className="mb-3 text-[18px] font-semibold leading-[1.4] text-text [text-wrap:pretty] lg:text-[19px]">
        {question}
      </p>
      <div className="flex flex-col gap-2">
        {options.map((option, i) => {
          const isPicked = selected === i
          const showState = answered && result.answer === i
          return (
            <button
              key={i}
              type="button"
              disabled={solvedCorrectly || submit.isPending}
              onClick={() => {
                setSelected(i)
                if (!solvedCorrectly) submit.mutate(i)
              }}
              className={cn(
                // min-height 48px — тап-таргет, а не декоративная высота.
                'flex min-h-[48px] w-full items-center gap-3 rounded-xl border px-3.5 text-left text-[16px] font-medium transition-colors',
                showState && result.correct
                  ? 'border-green bg-green/[0.12] text-text'
                  : showState
                    ? 'border-red bg-red/[0.12] text-text'
                    : isPicked
                      ? 'border-amber bg-amber/[0.08] text-text'
                      : 'border-glass-border bg-tint text-text hover:border-amber/40',
                (solvedCorrectly || submit.isPending) && 'cursor-default',
              )}
            >
              <span
                className={cn(
                  'flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full text-xs font-bold',
                  showState && result.correct
                    ? 'bg-green-deep text-bg'
                    : showState
                      ? 'bg-red text-bg'
                      : 'border border-glass-border text-text2',
                )}
              >
                {showState ? (
                  result.correct ? (
                    <Check className="h-3.5 w-3.5" />
                  ) : (
                    <X className="h-3.5 w-3.5" />
                  )
                ) : (
                  LETTERS[i] ?? i + 1
                )}
              </span>
              {option}
            </button>
          )
        })}
      </div>
      {answered && !solvedCorrectly && !lessonCompleted && (
        <p className="mt-3 text-[15px] font-medium leading-[1.5] text-text">
          Неверно — попробуйте другой вариант.
        </p>
      )}
      {answered && !solvedCorrectly && lessonCompleted && (
        <p className="mt-3 text-[15px] leading-[1.5] text-text2">
          Урок завершён — ответ учтён.
        </p>
      )}
      {solvedCorrectly && (
        <p className="mt-3 text-[15px] font-medium leading-[1.5] text-text">Верно!</p>
      )}
    </div>
  )
}
