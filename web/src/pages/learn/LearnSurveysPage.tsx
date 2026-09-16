import {
  Archive,
  ArrowLeft,
  BarChart3,
  Check,
  ClipboardList,
  Download,
  Plus,
  Send,
  Trash2,
  Users,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AudiencePicker, useAudienceDraft } from '@/components/learn/AudiencePicker'
import { SurveyQuestionsEditor } from '@/components/learn/SurveyQuestionsEditor'
import { QueryError } from '@/components/QueryError'
import { ActionRow } from '@/components/ui/ActionRow'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { Input, Textarea } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { MeterRow } from '@/components/ui/MeterRow'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useSurveyMutation, useSurveys } from '@/hooks/useLearn'
import { audienceDraftProblem } from '@/lib/audienceHints'
import { cn } from '@/lib/cn'
import {
  CONTENT_STATUS_LABEL,
  learnApi,
  type AnswerValue,
  type QuestionDraft,
  type QuestionType,
  type Survey,
  type SurveyResults,
} from '@/lib/learn'
import { nbsp } from '@/lib/typography'

/**
 * Опросы по макету «Урок — редизайн» (route surveys): список группами
 * «Активные / Остальные» (активные — открытые и не пройденные), прохождение и
 * экран «Ответ записан» — ОТДЕЛЬНЫЙ маршрут `/learn/surveys/:id` (раньше —
 * диалог): назад «Опросы», подпись об анонимности словами, шкала eNPS 0–10
 * кнопками 44px с подсказкой «Промоутер / Нейтральный / Критик», кнопка
 * «Осталось ответов: N» → «Отправить». Анонимность — свойство модели и главный
 * вопрос доверия, поэтому она подписана чипом, а не подразумевается.
 */

const DIMENSION_LABEL: Record<string, string> = {
  '': 'Без среза',
  store_id: 'По точкам',
  position_id: 'По должностям',
  franchisee_id: 'По франчайзи',
  department_id: 'По отделам',
  org_role: 'По контурам',
}

/** Ряд действий: 48px на телефоне, 36px в плотной ленте десктопа. */
const ACTION_BTN =
  'h-12 rounded-xl px-5 text-[15px] lg:h-9 lg:rounded-[10px] lg:px-3.5 lg:text-[13px]'
const GHOST_BTN = cn(ACTION_BTN, 'bg-transparent')

function surveyMeta(survey: Survey, manager: boolean): string {
  return nbsp(
    [
      survey.kind === 'enps' ? 'eNPS' : survey.kind === 'pulse' ? 'пульс' : null,
      `ответили: ${survey.participants}`,
      manager && survey.status !== 'published' ? CONTENT_STATUS_LABEL[survey.status] : null,
    ]
      .filter(Boolean)
      .join(' · '),
  )
}

// ─── Список ──────────────────────────────────────────────────────────────────

export function LearnSurveysPage() {
  const [params] = useSearchParams()
  const [builderSurvey, setBuilderSurvey] = useState<Survey | 'new' | null>(null)
  const [resultsSurvey, setResultsSurvey] = useState<Survey | null>(null)

  const probe = useSurveys(false)
  const canManage =
    probe.data !== undefined && ['admin', 'publisher', 'author'].includes(probe.data.content_role)
  const managed = useSurveys(true, canManage)
  const data = canManage ? (managed.data ?? probe.data) : probe.data

  const items = useMemo(() => data?.items ?? [], [data])
  const active = items.filter((s) => s.is_open_now && !s.participated)
  const rest = items.filter((s) => !(s.is_open_now && !s.participated))

  // Старый deep-link `?s=` (уведомления, закладки) → маршрут прохождения.
  const legacyRunner = params.get('s')
  if (legacyRunner) return <Navigate to={`/learn/surveys/${legacyRunner}`} replace />

  const counter = data ? nbsp(`Доступно пройти: ${active.length}`) : ''

  return (
    <div className="mx-auto max-w-[760px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
      <header className="flex flex-col gap-3.5 lg:flex-row lg:flex-wrap lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="mb-1 min-h-[1em] text-[12px] leading-[1.35] text-text2 lg:hidden">{counter}</p>
          <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
            Опросы
          </h1>
          <p className="mt-2.5 hidden text-[18px] leading-[1.6] text-text2 lg:block">
            {counter && `${counter}. `}
            Анонимные не сохраняют имя — результат виден только в агрегате по срезу.
          </p>
        </div>
        {canManage && (
          <Button
            onClick={() => setBuilderSurvey('new')}
            className="h-12 w-full rounded-xl text-[15px] lg:h-9 lg:w-auto lg:rounded-[10px] lg:px-3.5 lg:text-[13px]"
          >
            <Plus className="h-4 w-4" /> Опрос
          </Button>
        )}
      </header>

      <div className="mt-[18px] flex flex-col gap-5 lg:mt-[26px] lg:gap-[26px]">
        {probe.isLoading && <SkeletonRows rows={5} />}
        {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}
        {data && items.length === 0 && (
          <EmptyState
            layout="card"
            icon={<ClipboardList className="h-7 w-7" />}
            title="Опросов пока нет"
            text={
              canManage
                ? 'Создайте первый опрос — пульс смены, eNPS или свой набор вопросов.'
                : 'Когда компания запустит опрос, он появится здесь и на витрине.'
            }
          />
        )}

        {active.length > 0 && (
          <section className="flex flex-col gap-[9px] lg:gap-2.5">
            <h2 className="text-[12px] font-bold uppercase tracking-[0.08em] text-text2">Активные</h2>
            {active.map((s) => (
              <SurveyRow
                key={s.id}
                survey={s}
                muted={false}
                contentRole={data!.content_role}
                onEdit={() => setBuilderSurvey(s)}
                onResults={() => setResultsSurvey(s)}
              />
            ))}
          </section>
        )}
        {rest.length > 0 && (
          <section className="flex flex-col gap-[9px] lg:gap-2.5">
            <h2 className="text-[12px] font-bold uppercase tracking-[0.08em] text-text2">
              {active.length > 0 ? 'Остальные' : 'Все'}
            </h2>
            {rest.map((s) => (
              <SurveyRow
                key={s.id}
                survey={s}
                muted
                contentRole={data!.content_role}
                onEdit={() => setBuilderSurvey(s)}
                onResults={() => setResultsSurvey(s)}
              />
            ))}
          </section>
        )}
      </div>

      {builderSurvey !== null && (
        <SurveyBuilderDialog
          key={builderSurvey === 'new' ? 'new' : builderSurvey.id}
          survey={builderSurvey === 'new' ? null : builderSurvey}
          onClose={() => setBuilderSurvey(null)}
        />
      )}
      {resultsSurvey && (
        <SurveyResultsDialog key={resultsSurvey.id} survey={resultsSurvey} onClose={() => setResultsSurvey(null)} />
      )}
    </div>
  )
}

function SurveyRow({
  survey,
  muted,
  contentRole,
  onEdit,
  onResults,
}: {
  survey: Survey
  /** «Остальные»: заголовок приглушён — эти строки не требуют действия. */
  muted: boolean
  contentRole: string
  onEdit: () => void
  onResults: () => void
}) {
  const isPublisher = ['admin', 'publisher'].includes(contentRole)
  const canManage = isPublisher || contentRole === 'author'
  const setStatus = useSurveyMutation((s: string) => learnApi.setSurveyStatus(survey.id, s as never))
  const canRun = survey.is_open_now && !survey.participated

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-[14px] border border-hair bg-tint px-3.5 py-3">
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            'block text-[16px] font-semibold leading-[1.35] [text-wrap:pretty] lg:text-[17px]',
            muted ? 'text-text2' : 'text-text',
          )}
        >
          {survey.title}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-[7px] lg:gap-2">
          {survey.is_anonymous && (
            <span className="inline-flex h-[22px] items-center rounded-md bg-surface px-[7px] text-[12px] font-semibold text-text">
              анонимный
            </span>
          )}
          <span className="text-[13px] text-text2 lg:text-[14px]">{surveyMeta(survey, canManage)}</span>
        </span>
      </span>
      {canRun && (
        <Link
          to={`/learn/surveys/${survey.id}`}
          className="inline-flex min-h-11 shrink-0 items-center justify-center rounded-[11px] bg-amber px-[18px] text-[15px] font-semibold text-on-amber hover:bg-amber/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 focus-visible:ring-offset-2 focus-visible:ring-offset-bg lg:min-h-10 lg:rounded-[10px]"
        >
          Пройти
        </Link>
      )}
      {survey.participated && (
        <span className="inline-flex shrink-0 items-center gap-1.5 text-[14px] text-green-deep">
          <Check className="h-4 w-4" /> пройден
        </span>
      )}
      {canManage && (
        <ActionRow className="mt-0 w-full">
          <Button variant="secondary" className={GHOST_BTN} onClick={onEdit}>
            Изменить
          </Button>
          {isPublisher && (
            <Button variant="secondary" className={GHOST_BTN} onClick={onResults}>
              <BarChart3 className="h-4 w-4" /> Результаты
            </Button>
          )}
          {isPublisher && survey.status === 'published' && (
            <Button
              variant="secondary"
              className={GHOST_BTN}
              disabled={setStatus.isPending}
              onClick={() => void setStatus.mutateAsync('archived').then(() => toast.success('Опрос в архиве'))}
            >
              <Archive className="h-4 w-4" /> В архив
            </Button>
          )}
          {isPublisher && survey.status !== 'published' && survey.status !== 'archived' && survey.questions.length > 0 && (
            <Button
              className={ACTION_BTN}
              disabled={setStatus.isPending}
              onClick={() => void setStatus.mutateAsync('published').then(() => toast.success('Опрос опубликован'))}
            >
              <Send className="h-3.5 w-3.5" /> Опубликовать
            </Button>
          )}
        </ActionRow>
      )}
    </div>
  )
}

// ─── Прохождение: отдельный маршрут ──────────────────────────────────────────

export function LearnSurveyRunPage() {
  const { surveyId = '' } = useParams()
  const navigate = useNavigate()
  const [survey, setSurvey] = useState<Survey | null>(null)
  const [error, setError] = useState(false)
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({})
  const [sent, setSent] = useState(false)

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
  const missing = survey?.questions.filter((q) => q.required && !(q.id in answers)).length ?? 0

  const back = () => navigate('/learn/surveys')

  if (sent || survey?.participated) {
    return (
      <div className="mx-auto flex min-h-[70vh] max-w-[760px] flex-col items-center justify-center gap-3.5 px-6 py-7 text-center lg:py-16">
        <span className="flex h-16 w-16 items-center justify-center rounded-full bg-green-deep text-bg">
          <Check className="h-[30px] w-[30px]" strokeWidth={2.4} />
        </span>
        <h1 className="font-display text-[22px] font-bold leading-[1.25] text-text lg:text-[24px]">
          {sent ? 'Ответ записан' : 'Вы уже прошли этот опрос'}
        </h1>
        <p className="max-w-[300px] text-[16px] leading-[1.6] text-text2 [text-wrap:pretty] lg:max-w-[420px] lg:text-[17px]">
          {sent
            ? survey?.is_anonymous
              ? 'Спасибо. Итоги опроса появятся у руководителя, ваш ответ остаётся анонимным.'
              : 'Спасибо. Итоги опроса появятся у руководителя.'
            : 'Спасибо — ответы уже учтены. Повторно опрос не проходят.'}
        </p>
        <button
          type="button"
          onClick={back}
          className="inline-flex min-h-12 items-center justify-center rounded-xl border border-hair px-[22px] text-[15px] font-semibold text-text hover:border-amber/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:min-h-11 lg:rounded-[11px] lg:px-5"
        >
          К списку опросов
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[760px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
      <button
        type="button"
        onClick={back}
        className="-ml-2.5 mb-1 inline-flex min-h-11 items-center gap-[7px] rounded-lg px-2.5 text-[15px] font-semibold text-text hover:text-amber focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:mb-5 lg:min-h-10"
      >
        <ArrowLeft className="h-[17px] w-[17px]" strokeWidth={2.2} /> Опросы
      </button>

      {error && <QueryError onRetry={() => window.location.reload()} />}
      {!survey && !error && <SkeletonRows rows={6} />}

      {survey && (
        <form
          className="flex flex-col gap-[18px] lg:gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            if (missing > 0) return
            void submit.mutateAsync(undefined as never).then(() => setSent(true))
          }}
        >
          <div>
            <h1 className="font-display text-[24px] font-bold leading-[1.22] tracking-[0.01em] text-text lg:text-[28px] lg:leading-[1.2]">
              {survey.title}
            </h1>
            {(survey.description || survey.is_anonymous) && (
              <p className="mt-2 text-[15px] leading-[1.5] text-text2 lg:text-[16px] lg:leading-[1.55]">
                {[survey.description, survey.is_anonymous ? 'Опрос анонимный — ответы не связываются с вами.' : null]
                  .filter(Boolean)
                  .join(' ')}
              </p>
            )}
          </div>

          {survey.questions.map((q, i) => (
            <QuestionField
              key={q.id}
              index={i + 1}
              question={q}
              value={answers[q.id]}
              onChange={(v) => setAnswer(q.id, v)}
            />
          ))}

          <button
            type="submit"
            disabled={missing > 0 || submit.isPending}
            aria-disabled={missing > 0}
            className={cn(
              'inline-flex min-h-12 items-center justify-center self-start rounded-xl px-[22px] text-[15px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
              'w-full lg:w-auto',
              missing > 0 || submit.isPending
                ? 'cursor-not-allowed bg-surface text-text2'
                : 'bg-amber text-on-amber hover:bg-amber/90',
            )}
          >
            {submit.isPending ? 'Отправляем…' : missing > 0 ? nbsp(`Осталось ответов: ${missing}`) : 'Отправить'}
          </button>
          {survey.is_anonymous && (
            <p className="text-[13px] leading-[1.5] text-text2">
              Ответы анонимны: имя не сохраняется, результат виден только в агрегате по срезу.
            </p>
          )}
        </form>
      )}
    </div>
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
  const optionRow =
    'flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border border-hair bg-tint px-3.5 text-[16px] text-text has-[:checked]:border-amber/55 has-[:checked]:bg-amber/[0.08]'
  return (
    <fieldset className="flex flex-col gap-2.5 lg:gap-3">
      <legend className="mb-2.5 text-[18px] leading-[1.55] text-text [text-wrap:pretty] lg:mb-3 lg:text-[20px] lg:leading-[1.5]">
        <span className="text-text2">{index}. </span>
        {question.prompt}
        {!question.required && <span className="text-text2"> Необязательно</span>}
      </legend>
      {question.qtype === 'single' && (
        <div className="flex flex-col gap-2">
          {opts.map((opt, i) => (
            <label key={i} className={optionRow}>
              <input
                type="radio"
                name={question.id}
                checked={(value as { option?: number })?.option === i}
                onChange={() => onChange({ option: i })}
                className="h-[18px] w-[18px] accent-[#FFB200]"
              />
              {opt}
            </label>
          ))}
        </div>
      )}
      {question.qtype === 'multi' && (
        <div className="flex flex-col gap-2">
          {opts.map((opt, i) => {
            const selected = (value as { options?: number[] })?.options ?? []
            return (
              <label key={i} className={optionRow}>
                <input
                  type="checkbox"
                  checked={selected.includes(i)}
                  onChange={(e) =>
                    onChange({
                      options: e.target.checked ? [...selected, i] : selected.filter((x) => x !== i),
                    })
                  }
                  className="h-[18px] w-[18px] accent-[#FFB200]"
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
          placeholder="Свободный ответ"
          className="min-h-24 rounded-xl border-hair bg-tint px-3 py-3 text-[16px] leading-[1.5] lg:min-h-[104px]"
        />
      )}
      {(question.qtype === 'scale' || question.qtype === 'enps') && (
        <ScalePicker
          min={question.qtype === 'enps' ? 0 : (question.options?.min ?? 1)}
          max={question.qtype === 'enps' ? 10 : (question.options?.max ?? 5)}
          enps={question.qtype === 'enps'}
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
  enps,
  value,
  onChange,
}: {
  min: number
  max: number
  enps: boolean
  value: number | undefined
  onChange: (v: number) => void
}) {
  const values = Array.from({ length: max - min + 1 }, (_, i) => min + i)
  const hint =
    value === undefined
      ? `Выберите балл от ${min} до ${max}`
      : enps
        ? value >= 9
          ? 'Промоутер: 9–10'
          : value >= 7
            ? 'Нейтральный: 7–8'
            : 'Критик: 0–6'
        : `Выбрано: ${value}`
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap gap-1.5 lg:gap-[7px]" role="radiogroup" aria-label="Балл">
        {values.map((v) => (
          <button
            key={v}
            type="button"
            role="radio"
            aria-checked={value === v}
            onClick={() => onChange(v)}
            className={cn(
              'flex h-11 min-w-11 flex-1 items-center justify-center rounded-[10px] border text-[16px] font-semibold transition-colors',
              value === v ? 'border-amber bg-amber text-on-amber' : 'border-hair bg-transparent text-text hover:border-amber/40',
            )}
          >
            {v}
          </button>
        ))}
      </div>
      <p className="text-[14px] text-text2 lg:text-[15px]">{hint}</p>
    </div>
  )
}

// ─── Конструктор ─────────────────────────────────────────────────────────────

function SurveyBuilderDialog({ survey, onClose }: { survey: Survey | null; onClose: () => void }) {
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
    const saved = isNew ? await learnApi.createSurvey(meta) : await learnApi.updateSurvey(survey.id, meta)
    if (!published && questions.length > 0) {
      await learnApi.replaceQuestions(saved.id, questions)
    }
    return saved
  })
  const setStatus = useSurveyMutation((s: string) => learnApi.setSurveyStatus(survey!.id, s as never))
  const remove = useSurveyMutation(() => learnApi.deleteSurvey(survey!.id))

  const submit = () => {
    if (!title.trim()) return
    void save.mutateAsync(undefined as never).then(() => {
      toast.success('Сохранено')
      onClose()
    })
  }

  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={isNew ? 'Новый опрос' : survey.title}
      description={
        published
          ? 'Опрос опубликован — вопросы и анонимность заморожены: ответы должны оставаться сопоставимыми.'
          : isNew
            ? 'Опрос создаётся черновиком. Анонимность решается до публикации и потом не меняется.'
            : undefined
      }
      desktopWidth={680}
      footer={
        <>
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
              onClick={() => void setStatus.mutateAsync('archived').then(() => onClose())}
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
              onClick={() => void remove.mutateAsync(undefined as never).then(() => onClose())}
            >
              <Trash2 className="h-3.5 w-3.5" /> Удалить
            </Button>
          )}
          <span className="flex-1" />
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button type="button" onClick={submit} disabled={!title.trim() || save.isPending}>
            Сохранить
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sv-title">Название</Label>
          <Input
            id="sv-title"
            autoFocus={isNew}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="h-12 text-[15px] lg:h-11"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sv-desc">Описание</Label>
          <Textarea id="sv-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="sv-kind">Тип</Label>
            <Select
              id="sv-kind"
              value={kind}
              onChange={(e) => setKind(e.target.value as never)}
              className="h-12 text-[15px] lg:h-11"
            >
              <option value="standard">Обычный</option>
              <option value="pulse">Пульс</option>
              <option value="enps">eNPS</option>
            </Select>
          </div>
          <label className="flex min-h-11 cursor-pointer items-center gap-2.5 self-end text-[15px] text-text">
            <input
              type="checkbox"
              checked={anonymous}
              disabled={published}
              onChange={(e) => setAnonymous(e.target.checked)}
              className="h-[18px] w-[18px] accent-[#FFB200]"
            />
            Анонимный
          </label>
        </div>

        <SurveyQuestionsEditor questions={questions} onChange={setQuestions} disabled={published} />

        {/* ОС 19.08: «опубликованный опрос не правится и не удаляется» —
            ограничение намеренное (ответы уже собраны), объясняем его вслух. */}
        {published && (
          <p className="text-[13px] leading-[1.45] text-text2">
            Удалить опубликованный опрос нельзя — ответы уже собраны, и статистика перестала бы
            сходиться. Отправьте его в архив: он исчезнет у сотрудников, а результаты сохранятся.
          </p>
        )}
      </form>
      {audienceOpen && survey && <SurveyAudienceDialog survey={survey} onClose={() => setAudienceOpen(false)} />}
    </ResponsiveDialog>
  )
}

function SurveyAudienceDialog({ survey, onClose }: { survey: Survey; onClose: () => void }) {
  const audience = useAudienceDraft(survey.audience_id)
  const { value, setValue } = audience
  const save = useSurveyMutation(() => learnApi.setSurveyAudience(survey.id, value))
  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={`Кому виден «${survey.title}»`}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            type="button"
            disabled={save.isPending || !audience.ready || audienceDraftProblem(value) !== null}
            onClick={() =>
              void save.mutateAsync(undefined as never).then(() => {
                toast.success('Аудитория обновлена')
                onClose()
              })
            }
          >
            Сохранить
          </Button>
        </>
      }
    >
      {audience.loading ? (
        <SkeletonRows rows={3} />
      ) : (
        <>
          {audience.failed && (
            <p className="text-[14px] text-red">
              Не удалось загрузить текущие правила — сохранение перезапишет их.
            </p>
          )}
          <AudiencePicker value={value} onChange={setValue} extraLabels={audience.extraLabels} />
        </>
      )}
    </ResponsiveDialog>
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
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={`Результаты — «${survey.title}»`}
      description={
        results
          ? nbsp(
              `Ответили ${results.participants} из ${results.audience_size}` +
                (survey.is_anonymous ? ' · анонимный: маленькие группы срезов скрываются' : ''),
            )
          : undefined
      }
      desktopWidth={680}
      footer={
        <>
          <Button
            type="button"
            variant="secondary"
            className="bg-transparent"
            disabled={!results}
            onClick={() => void learnApi.downloadSurveyCsv(survey.id, dimension || undefined)}
          >
            <Download className="h-4 w-4" /> CSV
          </Button>
          <span className="flex-1" />
          <Button type="button" variant="secondary" onClick={onClose}>
            Закрыть
          </Button>
        </>
      }
    >
      <Select value={dimension} onChange={(e) => setDimension(e.target.value)} className="h-11 w-full sm:w-56">
        {Object.entries(DIMENSION_LABEL).map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </Select>
      {error && <p className="text-[14px] text-red">Не удалось загрузить результаты.</p>}
      {!results && !error && <SkeletonRows rows={5} />}
      {results &&
        results.questions.map((q) => (
          <div key={q.question_id} className="flex flex-col gap-2.5 rounded-xl border border-hair bg-tint p-3.5">
            <p className="text-[15px] font-semibold leading-[1.4] text-text">{q.prompt}</p>
            <p className="text-[13px] text-text2">
              Ответов: {q.total_answers}
              {q.enps_score !== null && (
                <span className="ml-2 font-semibold text-text">
                  eNPS {q.enps_score > 0 ? '+' : ''}
                  {q.enps_score}
                </span>
              )}
            </p>
            {dimension === '' ? (
              <Distribution
                qtype={q.qtype}
                distribution={q.distribution}
                options={survey.questions.find((x) => x.id === q.question_id)?.options?.options}
                total={q.total_answers}
              />
            ) : (
              <div className="flex flex-col gap-2.5">
                {Object.entries(q.groups).map(([group, entry]) => (
                  <div key={group} className="rounded-lg bg-surface p-2.5">
                    <p className="mb-1.5 text-[13px] font-semibold text-text2">{group}</p>
                    {entry === 'suppressed' ? (
                      <p className="text-[13px] italic text-text2">Недостаточно ответов для показа (анонимность)</p>
                    ) : (
                      <Distribution
                        qtype={q.qtype}
                        distribution={entry.distribution}
                        options={survey.questions.find((x) => x.id === q.question_id)?.options?.options}
                        total={entry.total}
                        enps={entry.enps_score}
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
            {q.qtype === 'open' && q.texts.length > 0 && (
              <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto">
                {q.texts.map((t, i) => (
                  <li key={i} className="rounded-lg bg-surface px-2.5 py-1.5 text-[13px] leading-[1.45] text-text2">
                    {t}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
    </ResponsiveDialog>
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
  const entries = Object.entries(distribution).sort((a, b) => Number(a[0]) - Number(b[0]))
  if (entries.length === 0) return <p className="text-[13px] text-text2">Нет ответов.</p>
  return (
    <div className="flex flex-col gap-1.5">
      {enps !== undefined && enps !== null && (
        <p className="text-[13px] font-semibold text-text">
          eNPS {enps > 0 ? '+' : ''}
          {enps}
        </p>
      )}
      {entries.map(([key, count]) => {
        const label =
          qtype === 'single' || qtype === 'multi' ? (options?.[Number(key)] ?? `Вариант ${Number(key) + 1}`) : key
        const pct = total > 0 ? Math.round((100 * count) / total) : 0
        return (
          <MeterRow
            key={key}
            label={
              <span className="block truncate" title={label}>
                {label}
              </span>
            }
            pct={pct}
            value={`${count} · ${pct}%`}
            labelWidth={qtype === 'single' || qtype === 'multi' ? 132 : 40}
          />
        )
      })}
    </div>
  )
}

