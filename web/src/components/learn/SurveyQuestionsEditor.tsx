import { Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import {
  QUESTION_TYPE_LABEL,
  type QuestionDraft,
  type QuestionType,
} from '@/lib/learn'

/**
 * Редактор списка вопросов опроса — вынесен из SurveyBuilderDialog
 * (LearnSurveysPage), используется также в SurveyEmbedDialog редактора
 * урока (ОС 12.08: «создать опрос прямо из текста»).
 */
export function SurveyQuestionsEditor({
  questions,
  onChange,
  disabled = false,
}: {
  questions: QuestionDraft[]
  onChange: (questions: QuestionDraft[]) => void
  disabled?: boolean
}) {
  const updateQuestion = (i: number, patch: Partial<QuestionDraft>) =>
    onChange(questions.map((q, idx) => (idx === i ? { ...q, ...patch } : q)))

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wider text-text3">Вопросы</p>
      {questions.map((q, i) => (
        <div key={i} className="space-y-2 rounded-lg border border-glass-border p-3">
          <div className="flex gap-2">
            <Select
              className="w-44"
              value={q.qtype}
              disabled={disabled}
              onChange={(e) => {
                const qtype = e.target.value as QuestionType
                updateQuestion(i, {
                  qtype,
                  options:
                    qtype === 'single' || qtype === 'multi'
                      ? { options: q.options?.options ?? ['', ''] }
                      : qtype === 'scale'
                        ? { min: 1, max: 5 }
                        : null,
                })
              }}
            >
              {Object.entries(QUESTION_TYPE_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
            <Input
              className="flex-1"
              value={q.prompt}
              disabled={disabled}
              onChange={(e) => updateQuestion(i, { prompt: e.target.value })}
              placeholder="Текст вопроса…"
            />
            {!disabled && (
              <button
                type="button"
                title="Удалить вопрос"
                className="rounded p-1.5 text-text3 hover:text-red"
                onClick={() => onChange(questions.filter((_, idx) => idx !== i))}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
          {(q.qtype === 'single' || q.qtype === 'multi') && (
            <div className="space-y-1 pl-2">
              {(q.options?.options ?? []).map((opt, oi) => (
                <div key={oi} className="flex items-center gap-2">
                  <Input
                    className="h-8"
                    value={opt}
                    disabled={disabled}
                    onChange={(e) => {
                      const options = [...(q.options?.options ?? [])]
                      options[oi] = e.target.value
                      updateQuestion(i, { options: { options } })
                    }}
                    placeholder={`Вариант ${oi + 1}`}
                  />
                  {!disabled && (q.options?.options?.length ?? 0) > 2 && (
                    <button
                      type="button"
                      className="text-text3 hover:text-red"
                      onClick={() =>
                        updateQuestion(i, {
                          options: {
                            options: (q.options?.options ?? []).filter((_, x) => x !== oi),
                          },
                        })
                      }
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              ))}
              {!disabled && (
                <Button
                  type="button"
                  variant="secondary"
                  className="h-7 text-xs"
                  onClick={() =>
                    updateQuestion(i, {
                      options: { options: [...(q.options?.options ?? []), ''] },
                    })
                  }
                >
                  <Plus className="h-3 w-3" /> Вариант
                </Button>
              )}
            </div>
          )}
          <label className="flex cursor-pointer items-center gap-2 text-xs text-text2">
            <input
              type="checkbox"
              checked={q.required}
              disabled={disabled}
              onChange={(e) => updateQuestion(i, { required: e.target.checked })}
              className="h-3.5 w-3.5 accent-[#FFB200]"
            />
            Обязательный
          </label>
        </div>
      ))}
      {!disabled && (
        <Button
          type="button"
          variant="secondary"
          onClick={() =>
            onChange([
              ...questions,
              { qtype: 'single', prompt: '', options: { options: ['', ''] }, required: true },
            ])
          }
        >
          <Plus className="h-4 w-4" /> Вопрос
        </Button>
      )}
    </div>
  )
}

/** Клиентская валидация перед созданием (зеркалит серверные правила) —
 * не даём цепочке create→questions упасть на полпути (опрос-сирота). */
export function validateQuestions(questions: QuestionDraft[]): string | null {
  if (questions.length === 0) return 'Добавьте хотя бы один вопрос'
  for (const [i, q] of questions.entries()) {
    if (!q.prompt.trim()) return `Вопрос ${i + 1}: пустой текст`
    if (q.qtype === 'single' || q.qtype === 'multi') {
      const opts = (q.options?.options ?? []).map((o) => o.trim()).filter(Boolean)
      if (opts.length < 2 || opts.length > 20) {
        return `Вопрос ${i + 1}: нужно от 2 до 20 вариантов ответа`
      }
    }
  }
  return null
}
