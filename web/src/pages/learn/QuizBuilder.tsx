import { CircleHelp, GripVertical, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { Switch } from '@/components/ui/Switch'
import { useLessonQuizManage, useQuizMutation } from '@/hooks/useLearn'
import { cn } from '@/lib/cn'
import {
  learnApi,
  QUIZ_QUESTION_TYPE_LABEL,
  type QuizQuestionDraft,
  type QuizQuestionType,
  type QuizSettings,
} from '@/lib/learn'

/**
 * Конструктор теста урока (Ф3b): 5 типов вопросов, настройки порога/попыток/
 * shuffle. Сохранение — цельный PUT (replace вопросов); сданные попытки
 * хранят собственные снапшоты и не ломаются.
 */

const DEFAULT_SETTINGS: QuizSettings = {
  title: 'Проверка знаний',
  description: null,
  status: 'draft',
  pass_score_pct: 80,
  attempts_limit: 3,
  shuffle_questions: false,
  shuffle_options: true,
  show_correct_answers: true,
  is_required: true,
}

export function QuizBuilder({ lessonId }: { lessonId: string }) {
  const quizQuery = useLessonQuizManage(lessonId)
  const [enabled, setEnabled] = useState(false)
  const [settings, setSettings] = useState<QuizSettings>(DEFAULT_SETTINGS)
  const [questions, setQuestions] = useState<QuizQuestionDraft[]>([])
  const [editIndex, setEditIndex] = useState<number | 'new' | null>(null)

  // Подхват сохранённого теста при загрузке.
  useEffect(() => {
    const quiz = quizQuery.data
    if (quiz) {
      setEnabled(true)
      setSettings({
        title: quiz.title,
        description: quiz.description,
        status: quiz.status,
        pass_score_pct: quiz.pass_score_pct,
        attempts_limit: quiz.attempts_limit,
        shuffle_questions: quiz.shuffle_questions,
        shuffle_options: quiz.shuffle_options,
        show_correct_answers: quiz.show_correct_answers,
        is_required: quiz.is_required,
      })
      setQuestions(
        quiz.questions.map((q) => ({
          qtype: q.qtype,
          prompt: q.prompt,
          media_id: q.media_id,
          options: q.options,
          answer: q.answer,
          points: q.points,
        })),
      )
    }
  }, [quizQuery.data])

  const save = useQuizMutation((status: 'draft' | 'published') =>
    learnApi.upsertLessonQuiz(lessonId, { ...settings, status, questions }),
  )
  const remove = useQuizMutation(() => learnApi.deleteQuiz(quizQuery.data!.id))

  if (quizQuery.isLoading) return <SkeletonRows rows={2} />

  if (!enabled) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setEnabled(true)}>
        <CircleHelp className="h-4 w-4" /> Добавить тест к уроку
      </Button>
    )
  }

  const doSave = (status: 'draft' | 'published') => {
    if (status === 'published' && questions.length === 0) {
      toast.error('Добавьте хотя бы один вопрос')
      return
    }
    void save.mutateAsync(status).then(() => {
      setSettings((s) => ({ ...s, status }))
      toast.success(status === 'published' ? 'Тест опубликован' : 'Тест сохранён')
    })
  }

  return (
    <div className="space-y-3 rounded-lg border border-glass-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-text">
          <CircleHelp className="h-4 w-4 text-amber" /> Тест урока
          <span
            className={cn(
              'rounded px-1.5 py-0.5 text-[10px] font-medium',
              settings.status === 'published'
                ? 'bg-amber/15 text-amber'
                : 'bg-glass text-text3',
            )}
          >
            {settings.status === 'published' ? 'опубликован' : 'черновик'}
          </span>
        </p>
        {quizQuery.data && (
          <button
            type="button"
            title="Удалить тест"
            onClick={() => {
              if (!window.confirm('Удалить тест целиком (с попытками)?')) return
              void remove.mutateAsync(undefined as never).then(() => {
                setEnabled(false)
                setSettings(DEFAULT_SETTINGS)
                setQuestions([])
              })
            }}
            className="rounded p-1.5 text-text3 hover:text-red"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Label htmlFor="quiz-title">Название теста</Label>
          <Input
            id="quiz-title"
            value={settings.title}
            onChange={(e) => setSettings({ ...settings, title: e.target.value })}
            maxLength={255}
          />
        </div>
        <div>
          <Label htmlFor="quiz-pass">Порог сдачи, %</Label>
          <Input
            id="quiz-pass"
            type="number"
            min={1}
            max={100}
            value={settings.pass_score_pct}
            onChange={(e) =>
              setSettings({ ...settings, pass_score_pct: Number(e.target.value) || 80 })
            }
          />
        </div>
        <div>
          <Label htmlFor="quiz-attempts">Лимит попыток (пусто = без лимита)</Label>
          <Input
            id="quiz-attempts"
            type="number"
            min={1}
            max={50}
            value={settings.attempts_limit ?? ''}
            onChange={(e) =>
              setSettings({
                ...settings,
                attempts_limit: e.target.value === '' ? null : Number(e.target.value),
              })
            }
          />
        </div>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {(
          [
            ['shuffle_questions', 'перемешивать вопросы'],
            ['shuffle_options', 'перемешивать варианты'],
            ['show_correct_answers', 'показывать разбор после сдачи'],
            ['is_required', 'обязательный (гейтит следующий урок)'],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="flex items-center gap-2 text-xs text-text2">
            <Switch
              checked={settings[key]}
              onCheckedChange={(v) => setSettings({ ...settings, [key]: v })}
            />
            {label}
          </label>
        ))}
      </div>

      <div className="space-y-1.5">
        {questions.map((q, i) => (
          <div
            key={i}
            className="flex items-center gap-2 rounded-md border border-glass-border bg-glass px-2.5 py-1.5 text-sm"
          >
            <GripVertical className="h-4 w-4 shrink-0 text-text3" />
            <span className="w-5 shrink-0 text-center text-xs text-text3">{i + 1}</span>
            <span className="min-w-0 flex-1 truncate text-text">{q.prompt}</span>
            <span className="shrink-0 text-xs text-text3">
              {QUIZ_QUESTION_TYPE_LABEL[q.qtype]} · {q.points} б.
            </span>
            <button
              type="button"
              title="Редактировать вопрос"
              onClick={() => setEditIndex(i)}
              className="rounded p-1 text-text3 hover:text-text"
            >
              <Pencil className="h-4 w-4" />
            </button>
            <button
              type="button"
              title="Удалить вопрос"
              onClick={() => setQuestions((prev) => prev.filter((_, j) => j !== i))}
              className="rounded p-1 text-text3 hover:text-red"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={() => setEditIndex('new')}>
          <Plus className="h-4 w-4" /> Вопрос
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={save.isPending || !settings.title.trim()}
          onClick={() => doSave('draft')}
        >
          Сохранить черновик
        </Button>
        <Button
          size="sm"
          disabled={save.isPending || !settings.title.trim()}
          onClick={() => doSave('published')}
        >
          Опубликовать тест
        </Button>
      </div>

      {editIndex !== null && (
        <QuestionDialog
          initial={editIndex === 'new' ? null : questions[editIndex] ?? null}
          onClose={() => setEditIndex(null)}
          onSave={(draft) => {
            setQuestions((prev) =>
              editIndex === 'new'
                ? [...prev, draft]
                : prev.map((q, i) => (i === editIndex ? draft : q)),
            )
            setEditIndex(null)
          }}
        />
      )}
    </div>
  )
}

// ─── Диалог вопроса ──────────────────────────────────────────────────────────

function QuestionDialog({
  initial,
  onClose,
  onSave,
}: {
  initial: QuizQuestionDraft | null
  onClose: () => void
  onSave: (draft: QuizQuestionDraft) => void
}) {
  const [qtype, setQtype] = useState<QuizQuestionType>(initial?.qtype ?? 'single')
  const [prompt, setPrompt] = useState(initial?.prompt ?? '')
  const [points, setPoints] = useState(initial?.points ?? 1)
  const [options, setOptions] = useState<string[]>(
    (initial?.options.options as string[]) ?? ['', ''],
  )
  const [correct, setCorrect] = useState<number[]>(
    ((initial?.answer?.correct as number[]) ?? []).slice(),
  )
  const [pairs, setPairs] = useState<{ left: string; right: string }[]>(() => {
    const left = (initial?.options.left as string[]) ?? []
    const right = (initial?.options.right as string[]) ?? []
    const answerPairs = (initial?.answer?.pairs as [number, number][]) ?? []
    if (left.length) {
      return answerPairs.map(([li, ri]) => ({ left: left[li] ?? '', right: right[ri] ?? '' }))
    }
    return [
      { left: '', right: '' },
      { left: '', right: '' },
    ]
  })
  const [items, setItems] = useState<string[]>(
    (initial?.options.items as string[]) ?? ['', ''],
  )

  const buildDraft = (): QuizQuestionDraft | string => {
    if (!prompt.trim()) return 'Введите вопрос'
    if (qtype === 'single' || qtype === 'multi') {
      const filled = options.map((o) => o.trim()).filter(Boolean)
      if (filled.length < 2) return 'Минимум два варианта'
      const validCorrect = correct.filter((i) => i < filled.length)
      if (qtype === 'single' && validCorrect.length !== 1) return 'Отметьте один правильный'
      if (qtype === 'multi' && validCorrect.length === 0) return 'Отметьте правильные'
      return {
        qtype,
        prompt: prompt.trim(),
        options: { options: filled },
        answer: { correct: validCorrect.sort((a, b) => a - b) },
        points,
      }
    }
    if (qtype === 'match') {
      const filled = pairs.filter((p) => p.left.trim() && p.right.trim())
      if (filled.length < 2) return 'Минимум две пары'
      return {
        qtype,
        prompt: prompt.trim(),
        options: {
          left: filled.map((p) => p.left.trim()),
          right: filled.map((p) => p.right.trim()),
        },
        answer: { pairs: filled.map((_, i) => [i, i]) },
        points,
      }
    }
    if (qtype === 'order') {
      const filled = items.map((o) => o.trim()).filter(Boolean)
      if (filled.length < 2) return 'Минимум два элемента'
      return { qtype, prompt: prompt.trim(), options: { items: filled }, answer: null, points }
    }
    return { qtype: 'open', prompt: prompt.trim(), options: {}, answer: null, points }
  }

  const submit = () => {
    const draft = buildDraft()
    if (typeof draft === 'string') {
      toast.error(draft)
      return
    }
    onSave(draft)
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{initial ? 'Вопрос' : 'Новый вопрос'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <Label htmlFor="q-type">Тип</Label>
              <Select
                id="q-type"
                value={qtype}
                onChange={(e) => setQtype(e.target.value as QuizQuestionType)}
              >
                {(Object.keys(QUIZ_QUESTION_TYPE_LABEL) as QuizQuestionType[]).map((t) => (
                  <option key={t} value={t}>
                    {QUIZ_QUESTION_TYPE_LABEL[t]}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="q-points">Баллы</Label>
              <Input
                id="q-points"
                type="number"
                min={1}
                max={100}
                value={points}
                onChange={(e) => setPoints(Number(e.target.value) || 1)}
              />
            </div>
          </div>
          <div>
            <Label htmlFor="q-prompt">Вопрос</Label>
            <textarea
              id="q-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={2}
              className="flex w-full rounded-lg border border-glass-border bg-glass px-3 py-2 text-sm text-text focus-visible:border-amber focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber"
            />
          </div>

          {(qtype === 'single' || qtype === 'multi') && (
            <div className="space-y-1.5">
              <Label>Варианты (отметьте правильные)</Label>
              {options.map((option, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    type={qtype === 'single' ? 'radio' : 'checkbox'}
                    name="q-correct"
                    checked={correct.includes(i)}
                    onChange={() =>
                      setCorrect((prev) =>
                        qtype === 'single'
                          ? [i]
                          : prev.includes(i)
                            ? prev.filter((j) => j !== i)
                            : [...prev, i],
                      )
                    }
                    className="accent-amber"
                    aria-label={`Правильный — вариант ${i + 1}`}
                  />
                  <Input
                    value={option}
                    onChange={(e) =>
                      setOptions((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))
                    }
                    placeholder={`Вариант ${i + 1}`}
                  />
                  {options.length > 2 && (
                    <button
                      type="button"
                      aria-label="Убрать вариант"
                      onClick={() => {
                        setOptions((prev) => prev.filter((_, j) => j !== i))
                        setCorrect((prev) =>
                          prev.filter((j) => j !== i).map((j) => (j > i ? j - 1 : j)),
                        )
                      }}
                      className="rounded p-1.5 text-text3 hover:text-red"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>
              ))}
              {options.length < 10 && (
                <Button size="sm" variant="ghost" onClick={() => setOptions((p) => [...p, ''])}>
                  + вариант
                </Button>
              )}
            </div>
          )}

          {qtype === 'match' && (
            <div className="space-y-1.5">
              <Label>Пары (левое ↔ правое; правая колонка перемешается)</Label>
              {pairs.map((pair, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    value={pair.left}
                    onChange={(e) =>
                      setPairs((prev) =>
                        prev.map((p, j) => (j === i ? { ...p, left: e.target.value } : p)),
                      )
                    }
                    placeholder="Латте"
                  />
                  <span className="text-text3">↔</span>
                  <Input
                    value={pair.right}
                    onChange={(e) =>
                      setPairs((prev) =>
                        prev.map((p, j) => (j === i ? { ...p, right: e.target.value } : p)),
                      )
                    }
                    placeholder="250 мл"
                  />
                  {pairs.length > 2 && (
                    <button
                      type="button"
                      aria-label="Убрать пару"
                      onClick={() => setPairs((prev) => prev.filter((_, j) => j !== i))}
                      className="rounded p-1.5 text-text3 hover:text-red"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>
              ))}
              {pairs.length < 8 && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setPairs((p) => [...p, { left: '', right: '' }])}
                >
                  + пара
                </Button>
              )}
            </div>
          )}

          {qtype === 'order' && (
            <div className="space-y-1.5">
              <Label>Элементы В ПРАВИЛЬНОМ порядке (сотруднику перемешаются)</Label>
              {items.map((item, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="w-5 text-center text-xs text-text3">{i + 1}</span>
                  <Input
                    value={item}
                    onChange={(e) =>
                      setItems((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))
                    }
                    placeholder={`Шаг ${i + 1}`}
                  />
                  {items.length > 2 && (
                    <button
                      type="button"
                      aria-label="Убрать элемент"
                      onClick={() => setItems((prev) => prev.filter((_, j) => j !== i))}
                      className="rounded p-1.5 text-text3 hover:text-red"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>
              ))}
              {items.length < 10 && (
                <Button size="sm" variant="ghost" onClick={() => setItems((p) => [...p, ''])}>
                  + элемент
                </Button>
              )}
            </div>
          )}

          {qtype === 'open' && (
            <p className="text-xs text-text3">
              Открытый ответ проверяется вручную (HR/публикатор): до проверки тест
              остаётся «на проверке», баллы выставляет проверяющий.
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={submit}>Сохранить вопрос</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
