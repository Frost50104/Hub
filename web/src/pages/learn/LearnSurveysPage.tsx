import {
  Archive,
  BarChart3,
  Check,
  ClipboardList,
  Pencil,
  Plus,
  Send,
  Trash2,
  Users,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AudiencePicker, type AudienceValue } from '@/components/learn/AudiencePicker'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input, Textarea } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useSurveyMutation, useSurveys } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import {
  CONTENT_STATUS_LABEL,
  learnApi,
  QUESTION_TYPE_LABEL,
  type AnswerValue,
  type QuestionDraft,
  type QuestionType,
  type Survey,
  type SurveyResults,
} from '@/lib/learn'

const DIMENSION_LABEL: Record<string, string> = {
  '': 'Без среза',
  store_id: 'По магазинам',
  position_id: 'По должностям',
  franchisee_id: 'По франчайзи',
  department_id: 'По отделам',
  org_role: 'По контурам',
}

export function LearnSurveysPage() {
  const isDesktop = useIsDesktop()
  const [params, setParams] = useSearchParams()
  const [builderSurvey, setBuilderSurvey] = useState<Survey | 'new' | null>(null)
  const [resultsSurvey, setResultsSurvey] = useState<Survey | null>(null)

  const probe = useSurveys(false)
  const canManage =
    probe.data !== undefined && ['admin', 'publisher', 'author'].includes(probe.data.content_role)
  const managed = useSurveys(true, canManage)
  const data = canManage ? (managed.data ?? probe.data) : probe.data

  const runnerId = params.get('s')
  const setRunner = (id: string | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('s', id)
    else next.delete('s')
    setParams(next, { replace: true })
  }

  const active = (data?.items ?? []).filter((s) => s.is_open_now && !s.participated)
  const done = (data?.items ?? []).filter((s) => s.participated)
  const rest = (data?.items ?? []).filter(
    (s) => !active.includes(s) && !done.includes(s),
  )

  return (
    <div className="mx-auto max-w-3xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Опросы" />}
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex items-center justify-between gap-2">
          {isDesktop && <h1 className="font-display text-2xl font-bold text-text">Опросы</h1>}
          {canManage && (
            <Button onClick={() => setBuilderSurvey('new')}>
              <Plus className="h-4 w-4" /> Опрос
            </Button>
          )}
        </div>

        {probe.isLoading && <SkeletonRows rows={5} />}
        {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}
        {data && data.items.length === 0 && (
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <ClipboardList className="mx-auto h-8 w-8 text-text3" />
            <p className="mt-3 text-sm text-text2">Опросов пока нет.</p>
          </div>
        )}

        {active.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text3">
              Активные
            </h2>
            {active.map((s) => (
              <SurveyRow
                key={s.id}
                survey={s}
                contentRole={data!.content_role}
                onRun={() => setRunner(s.id)}
                onEdit={() => setBuilderSurvey(s)}
                onResults={() => setResultsSurvey(s)}
              />
            ))}
          </section>
        )}
        {(rest.length > 0 || done.length > 0) && (
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text3">
              {active.length > 0 ? 'Остальные' : 'Все'}
            </h2>
            {[...rest, ...done].map((s) => (
              <SurveyRow
                key={s.id}
                survey={s}
                contentRole={data!.content_role}
                onRun={() => setRunner(s.id)}
                onEdit={() => setBuilderSurvey(s)}
                onResults={() => setResultsSurvey(s)}
              />
            ))}
          </section>
        )}
      </div>

      {runnerId && (
        <SurveyRunnerDialog key={runnerId} surveyId={runnerId} onClose={() => setRunner(null)} />
      )}
      {builderSurvey !== null && (
        <SurveyBuilderDialog
          key={builderSurvey === 'new' ? 'new' : builderSurvey.id}
          survey={builderSurvey === 'new' ? null : builderSurvey}
          onClose={() => setBuilderSurvey(null)}
        />
      )}
      {resultsSurvey && (
        <SurveyResultsDialog
          key={resultsSurvey.id}
          survey={resultsSurvey}
          onClose={() => setResultsSurvey(null)}
        />
      )}
    </div>
  )
}

function SurveyRow({
  survey,
  contentRole,
  onRun,
  onEdit,
  onResults,
}: {
  survey: Survey
  contentRole: string
  onRun: () => void
  onEdit: () => void
  onResults: () => void
}) {
  const isPublisher = ['admin', 'publisher'].includes(contentRole)
  const canManage = isPublisher || contentRole === 'author'
  return (
    <div className="flex items-center gap-3 rounded-xl border border-glass-border bg-glass px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-text">
          {survey.title}
          {survey.is_anonymous && (
            <span className="ml-2 text-xs text-text3">анонимный</span>
          )}
        </p>
        <p className="truncate text-xs text-text3">
          {[
            survey.kind === 'enps' ? 'eNPS' : survey.kind === 'pulse' ? 'пульс' : null,
            `ответили: ${survey.participants}`,
            survey.status !== 'published' ? CONTENT_STATUS_LABEL[survey.status] : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </div>
      {survey.participated ? (
        <span className="flex items-center gap-1 text-xs text-green">
          <Check className="h-3.5 w-3.5" /> пройден
        </span>
      ) : survey.is_open_now ? (
        <Button onClick={onRun}>Пройти</Button>
      ) : null}
      {canManage && (
        <button
          title="Изменить"
          className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text"
          onClick={onEdit}
        >
          <Pencil className="h-4 w-4" />
        </button>
      )}
      {isPublisher && (
        <button
          title="Результаты"
          className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text"
          onClick={onResults}
        >
          <BarChart3 className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}

// ─── Прохождение ─────────────────────────────────────────────────────────────

function SurveyRunnerDialog({ surveyId, onClose }: { surveyId: string; onClose: () => void }) {
  const [survey, setSurvey] = useState<Survey | null>(null)
  const [error, setError] = useState(false)
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({})

  useEffect(() => {
    learnApi
      .survey(surveyId)
      .then(setSurvey)
      .catch(() => setError(true))
  }, [surveyId])

  const submit = useSurveyMutation(() =>
    learnApi.submitSurvey(
      surveyId,
      Object.entries(answers).map(([question_id, value]) => ({ question_id, value })),
    ),
  )

  const setAnswer = (questionId: string, value: AnswerValue) =>
    setAnswers((prev) => ({ ...prev, [questionId]: value }))

  const missing =
    survey?.questions.filter((q) => q.required && !(q.id in answers)).length ?? 0

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-xl overflow-y-auto">
        {error && <p className="text-sm text-red">Не удалось загрузить опрос.</p>}
        {!survey && !error && <SkeletonRows rows={5} />}
        {survey && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void submit.mutateAsync(undefined as never).then(() => {
                toast.success('Спасибо! Ответы записаны.')
                onClose()
              })
            }}
          >
            <DialogHeader>
              <DialogTitle>{survey.title}</DialogTitle>
              <DialogDescription>
                {[
                  survey.description,
                  survey.is_anonymous
                    ? 'Опрос анонимный — ответы не связываются с вами.'
                    : null,
                ]
                  .filter(Boolean)
                  .join(' ')}
              </DialogDescription>
            </DialogHeader>
            {survey.participated ? (
              <p className="text-sm text-green">Вы уже прошли этот опрос. Спасибо!</p>
            ) : (
              <div className="space-y-5">
                {survey.questions.map((q, i) => (
                  <QuestionField
                    key={q.id}
                    index={i + 1}
                    question={q}
                    value={answers[q.id]}
                    onChange={(v) => setAnswer(q.id, v)}
                  />
                ))}
              </div>
            )}
            <DialogFooter>
              <Button type="button" variant="secondary" onClick={onClose}>
                Закрыть
              </Button>
              {!survey.participated && (
                <Button type="submit" disabled={missing > 0 || submit.isPending}>
                  {missing > 0 ? `Осталось ответов: ${missing}` : 'Отправить'}
                </Button>
              )}
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

function QuestionField({
  index,
  question,
  value,
  onChange,
}: {
  index: number
  question: Survey['questions'][number]
  value: AnswerValue | undefined
  onChange: (v: AnswerValue) => void
}) {
  const opts = question.options?.options ?? []
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-medium text-text">
        {index}. {question.prompt}
        {question.required && <span className="text-red"> *</span>}
      </legend>
      {question.qtype === 'single' && (
        <div className="space-y-1">
          {opts.map((opt, i) => (
            <label
              key={i}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-sm text-text hover:bg-glass"
            >
              <input
                type="radio"
                name={question.id}
                checked={(value as { option?: number })?.option === i}
                onChange={() => onChange({ option: i })}
                className="h-4 w-4 accent-[#FFB200]"
              />
              {opt}
            </label>
          ))}
        </div>
      )}
      {question.qtype === 'multi' && (
        <div className="space-y-1">
          {opts.map((opt, i) => {
            const selected = (value as { options?: number[] })?.options ?? []
            return (
              <label
                key={i}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-sm text-text hover:bg-glass"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(i)}
                  onChange={(e) =>
                    onChange({
                      options: e.target.checked
                        ? [...selected, i]
                        : selected.filter((x) => x !== i),
                    })
                  }
                  className="h-4 w-4 accent-[#FFB200]"
                />
                {opt}
              </label>
            )
          })}
        </div>
      )}
      {question.qtype === 'open' && (
        <Textarea
          rows={3}
          value={(value as { text?: string })?.text ?? ''}
          onChange={(e) => onChange({ text: e.target.value })}
          placeholder="Ваш ответ…"
        />
      )}
      {(question.qtype === 'scale' || question.qtype === 'enps') && (
        <ScalePicker
          min={question.qtype === 'enps' ? 0 : (question.options?.min ?? 1)}
          max={question.qtype === 'enps' ? 10 : (question.options?.max ?? 5)}
          value={(value as { value?: number })?.value}
          onChange={(v) => onChange({ value: v })}
        />
      )}
    </fieldset>
  )
}

function ScalePicker({
  min,
  max,
  value,
  onChange,
}: {
  min: number
  max: number
  value: number | undefined
  onChange: (v: number) => void
}) {
  const values = Array.from({ length: max - min + 1 }, (_, i) => min + i)
  return (
    <div className="flex flex-wrap gap-1">
      {values.map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={cn(
            'h-9 min-w-9 rounded-lg border px-2 text-sm font-medium transition-colors',
            value === v
              ? 'border-amber bg-amber text-on-amber'
              : 'border-glass-border bg-glass text-text2 hover:border-amber/40',
          )}
        >
          {v}
        </button>
      ))}
    </div>
  )
}

// ─── Конструктор ─────────────────────────────────────────────────────────────

function SurveyBuilderDialog({
  survey,
  onClose,
}: {
  survey: Survey | null
  onClose: () => void
}) {
  const isNew = survey === null
  const published = survey?.published_at != null
  const [title, setTitle] = useState(survey?.title ?? '')
  const [description, setDescription] = useState(survey?.description ?? '')
  const [kind, setKind] = useState(survey?.kind ?? 'standard')
  const [anonymous, setAnonymous] = useState(survey?.is_anonymous ?? false)
  const [questions, setQuestions] = useState<QuestionDraft[]>([])
  const [audienceOpen, setAudienceOpen] = useState(false)

  // Список отдаёт опросы БЕЗ вопросов — при редактировании дочитываем полный.
  useEffect(() => {
    if (survey === null) return
    void learnApi.survey(survey.id).then((full) => {
      setQuestions(
        full.questions.map((q) => ({
          qtype: q.qtype,
          prompt: q.prompt,
          options: q.options,
          required: q.required,
        })),
      )
    })
  }, [survey])

  const save = useSurveyMutation(async () => {
    const meta = {
      title: title.trim(),
      description: description.trim() || null,
      kind,
      is_anonymous: anonymous,
    }
    const saved = isNew
      ? await learnApi.createSurvey(meta)
      : await learnApi.updateSurvey(survey.id, meta)
    if (!published && questions.length > 0) {
      await learnApi.replaceQuestions(saved.id, questions)
    }
    return saved
  })
  const setStatus = useSurveyMutation((s: string) =>
    learnApi.setSurveyStatus(survey!.id, s as never),
  )
  const remove = useSurveyMutation(() => learnApi.deleteSurvey(survey!.id))

  const updateQuestion = (i: number, patch: Partial<QuestionDraft>) =>
    setQuestions((prev) => prev.map((q, idx) => (idx === i ? { ...q, ...patch } : q)))

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (!title.trim()) return
            void save.mutateAsync(undefined as never).then(() => {
              toast.success('Сохранено')
              onClose()
            })
          }}
        >
          <DialogHeader>
            <DialogTitle>{isNew ? 'Новый опрос' : survey.title}</DialogTitle>
            {published && (
              <DialogDescription>
                Опрос опубликован — вопросы и анонимность заморожены (ответы должны
                оставаться сопоставимыми).
              </DialogDescription>
            )}
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="sv-title">Название</Label>
                <Input
                  id="sv-title"
                  autoFocus={isNew}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="sv-desc">Описание</Label>
                <Textarea
                  id="sv-desc"
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sv-kind">Тип</Label>
                <Select id="sv-kind" value={kind} onChange={(e) => setKind(e.target.value as never)}>
                  <option value="standard">Обычный</option>
                  <option value="pulse">Пульс</option>
                  <option value="enps">eNPS</option>
                </Select>
              </div>
              <label className="flex cursor-pointer items-center gap-2 self-end pb-2 text-sm text-text">
                <input
                  type="checkbox"
                  checked={anonymous}
                  disabled={published}
                  onChange={(e) => setAnonymous(e.target.checked)}
                  className="h-4 w-4 accent-[#FFB200]"
                />
                Анонимный
              </label>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-text3">
                Вопросы
              </p>
              {questions.map((q, i) => (
                <div key={i} className="space-y-2 rounded-lg border border-glass-border p-3">
                  <div className="flex gap-2">
                    <Select
                      className="w-44"
                      value={q.qtype}
                      disabled={published}
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
                      disabled={published}
                      onChange={(e) => updateQuestion(i, { prompt: e.target.value })}
                      placeholder="Текст вопроса…"
                    />
                    {!published && (
                      <button
                        type="button"
                        title="Удалить вопрос"
                        className="rounded p-1.5 text-text3 hover:text-red"
                        onClick={() =>
                          setQuestions((prev) => prev.filter((_, idx) => idx !== i))
                        }
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
                            disabled={published}
                            onChange={(e) => {
                              const options = [...(q.options?.options ?? [])]
                              options[oi] = e.target.value
                              updateQuestion(i, { options: { options } })
                            }}
                            placeholder={`Вариант ${oi + 1}`}
                          />
                          {!published && (q.options?.options?.length ?? 0) > 2 && (
                            <button
                              type="button"
                              className="text-text3 hover:text-red"
                              onClick={() =>
                                updateQuestion(i, {
                                  options: {
                                    options: (q.options?.options ?? []).filter(
                                      (_, x) => x !== oi,
                                    ),
                                  },
                                })
                              }
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                      ))}
                      {!published && (
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
                      disabled={published}
                      onChange={(e) => updateQuestion(i, { required: e.target.checked })}
                      className="h-3.5 w-3.5 accent-[#FFB200]"
                    />
                    Обязательный
                  </label>
                </div>
              ))}
              {!published && (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() =>
                    setQuestions((prev) => [
                      ...prev,
                      { qtype: 'single', prompt: '', options: { options: ['', ''] }, required: true },
                    ])
                  }
                >
                  <Plus className="h-4 w-4" /> Вопрос
                </Button>
              )}
            </div>
          </div>

          <DialogFooter className="flex-wrap">
            {!isNew && survey.status !== 'published' && (
              <Button
                type="button"
                disabled={setStatus.isPending || questions.length === 0}
                onClick={() =>
                  void setStatus.mutateAsync('published').then(() => {
                    toast.success('Опрос опубликован')
                    onClose()
                  })
                }
              >
                <Send className="h-3.5 w-3.5" /> Опубликовать
              </Button>
            )}
            {!isNew && survey.status === 'published' && (
              <Button
                type="button"
                variant="secondary"
                disabled={setStatus.isPending}
                onClick={() =>
                  void setStatus.mutateAsync('archived').then(() => onClose())
                }
              >
                <Archive className="h-3.5 w-3.5" /> В архив
              </Button>
            )}
            {!isNew && (
              <Button type="button" variant="secondary" onClick={() => setAudienceOpen(true)}>
                <Users className="h-3.5 w-3.5" /> Аудитория
              </Button>
            )}
            {!isNew && survey.published_at === null && (
              <Button
                type="button"
                variant="secondary"
                className="text-red"
                disabled={remove.isPending}
                onClick={() =>
                  void remove.mutateAsync(undefined as never).then(() => onClose())
                }
              >
                Удалить
              </Button>
            )}
            <div className="flex-1" />
            <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
              Отмена
            </Button>
            <Button type="submit" disabled={!title.trim() || save.isPending}>
              Сохранить
            </Button>
          </DialogFooter>
        </form>
        {audienceOpen && survey && (
          <SurveyAudienceDialog survey={survey} onClose={() => setAudienceOpen(false)} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function SurveyAudienceDialog({ survey, onClose }: { survey: Survey; onClose: () => void }) {
  const [value, setValue] = useState<AudienceValue>({
    is_all: survey.audience_id === null,
    rules: [],
  })
  const save = useSurveyMutation(() => learnApi.setSurveyAudience(survey.id, value))
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Кому виден «{survey.title}»</DialogTitle>
        </DialogHeader>
        <AudiencePicker value={value} onChange={setValue} />
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            type="button"
            disabled={save.isPending}
            onClick={() =>
              void save.mutateAsync(undefined as never).then(() => {
                toast.success('Аудитория обновлена')
                onClose()
              })
            }
          >
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Результаты ──────────────────────────────────────────────────────────────

function SurveyResultsDialog({ survey, onClose }: { survey: Survey; onClose: () => void }) {
  const [dimension, setDimension] = useState('')
  const [results, setResults] = useState<SurveyResults | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    setResults(null)
    learnApi
      .surveyResults(survey.id, dimension || undefined)
      .then(setResults)
      .catch(() => setError(true))
  }, [survey.id, dimension])

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Результаты — «{survey.title}»</DialogTitle>
          {results && (
            <DialogDescription>
              Ответили {results.participants} из {results.audience_size}
              {survey.is_anonymous &&
                ' · анонимный: маленькие группы срезов скрываются'}
            </DialogDescription>
          )}
        </DialogHeader>
        <Select value={dimension} onChange={(e) => setDimension(e.target.value)} className="w-56">
          {Object.entries(DIMENSION_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </Select>
        {error && <p className="text-sm text-red">Не удалось загрузить результаты.</p>}
        {!results && !error && <SkeletonRows rows={5} />}
        {results &&
          results.questions.map((q) => (
            <div key={q.question_id} className="space-y-2 rounded-lg border border-glass-border p-3">
              <p className="text-sm font-medium text-text">{q.prompt}</p>
              <p className="text-xs text-text3">
                Ответов: {q.total_answers}
                {q.enps_score !== null && (
                  <span className="ml-2 font-semibold text-amber">
                    eNPS {q.enps_score > 0 ? '+' : ''}
                    {q.enps_score}
                  </span>
                )}
              </p>
              {dimension === '' ? (
                <Distribution
                  qtype={q.qtype}
                  distribution={q.distribution}
                  options={
                    survey.questions.find((x) => x.id === q.question_id)?.options?.options
                  }
                  total={q.total_answers}
                />
              ) : (
                <div className="space-y-2">
                  {Object.entries(q.groups).map(([group, entry]) => (
                    <div key={group} className="rounded bg-surface/50 p-2">
                      <p className="mb-1 text-xs font-medium text-text2">{group}</p>
                      {entry === 'suppressed' ? (
                        <p className="text-xs italic text-text3">
                          Недостаточно ответов для показа (анонимность)
                        </p>
                      ) : (
                        <Distribution
                          qtype={q.qtype}
                          distribution={entry.distribution}
                          options={
                            survey.questions.find((x) => x.id === q.question_id)?.options
                              ?.options
                          }
                          total={entry.total}
                          enps={entry.enps_score}
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}
              {q.qtype === 'open' && q.texts.length > 0 && (
                <ul className="max-h-40 space-y-1 overflow-y-auto">
                  {q.texts.map((t, i) => (
                    <li key={i} className="rounded bg-surface/50 px-2 py-1 text-xs text-text2">
                      {t}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose}>
            Закрыть
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Distribution({
  qtype,
  distribution,
  options,
  total,
  enps,
}: {
  qtype: QuestionType
  distribution: Record<string, number>
  options: string[] | undefined
  total: number
  enps?: number
}) {
  const entries = Object.entries(distribution).sort(
    (a, b) => Number(a[0]) - Number(b[0]),
  )
  if (entries.length === 0) return <p className="text-xs text-text3">Нет ответов.</p>
  return (
    <div className="space-y-1">
      {enps !== undefined && enps !== null && (
        <p className="text-xs font-semibold text-amber">
          eNPS {enps > 0 ? '+' : ''}
          {enps}
        </p>
      )}
      {entries.map(([key, count]) => {
        const label =
          qtype === 'single' || qtype === 'multi'
            ? (options?.[Number(key)] ?? `Вариант ${Number(key) + 1}`)
            : key
        const pct = total > 0 ? Math.round((100 * count) / total) : 0
        return (
          <div key={key} className="flex items-center gap-2 text-xs">
            <span className="w-32 truncate text-text2" title={label}>
              {label}
            </span>
            <div className="h-2 flex-1 overflow-hidden rounded bg-surface">
              <div className="h-full bg-amber" style={{ width: `${pct}%` }} />
            </div>
            <span className="w-12 text-right text-text3">
              {count} · {pct}%
            </span>
          </div>
        )
      })}
    </div>
  )
}
