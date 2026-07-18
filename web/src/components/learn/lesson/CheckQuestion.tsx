import { useMutation } from '@tanstack/react-query'
import { Check, CircleHelp, X } from 'lucide-react'
import { useState } from 'react'

import { cn } from '@/lib/cn'
import { learnApi } from '@/lib/learn'

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
  onAnswered,
}: {
  lessonId: string
  blockId: string
  question: string
  options: string[]
  gateNext?: boolean
  initialAnswer?: { answer: number; correct: boolean }
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
        'my-3 rounded-lg border px-3 py-2.5',
        solvedCorrectly
          ? 'border-green/50 bg-green/5'
          : answered
            ? 'border-red/50 bg-red/5'
            : 'border-amber/40 bg-glass',
      )}
    >
      <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-text2">
        <CircleHelp className="h-3.5 w-3.5 text-amber" />
        Проверьте себя
        {gateNext && !solvedCorrectly && (
          <span className="rounded bg-amber/15 px-1.5 py-0.5 text-[10px] normal-case text-amber">
            нужен ответ для завершения урока
          </span>
        )}
      </p>
      <p className="mb-2 text-sm font-medium text-text">{question}</p>
      <div className="space-y-1">
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
                'flex w-full items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-sm transition-colors',
                showState && result.correct
                  ? 'border-green/60 bg-green/10 text-text'
                  : showState
                    ? 'border-red/60 bg-red/10 text-text'
                    : isPicked
                      ? 'border-amber/60 bg-amber/10 text-text'
                      : 'border-glass-border bg-surface text-text2 hover:border-amber/40 hover:text-text',
                (solvedCorrectly || submit.isPending) && 'cursor-default opacity-80',
              )}
            >
              <span
                className={cn(
                  'flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-[10px]',
                  showState && result.correct
                    ? 'border-green bg-green text-white'
                    : showState
                      ? 'border-red bg-red text-white'
                      : 'border-glass-border',
                )}
              >
                {showState ? (
                  result.correct ? (
                    <Check className="h-3 w-3" />
                  ) : (
                    <X className="h-3 w-3" />
                  )
                ) : null}
              </span>
              {option}
            </button>
          )
        })}
      </div>
      {answered && !solvedCorrectly && (
        <p className="mt-1.5 text-xs text-red">Неверно — попробуйте другой вариант.</p>
      )}
      {solvedCorrectly && <p className="mt-1.5 text-xs text-green">Верно!</p>}
    </div>
  )
}
