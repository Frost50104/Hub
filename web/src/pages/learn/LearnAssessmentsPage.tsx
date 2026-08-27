import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BadgeCheck, Import, Pencil, Plus, Trash2, Users, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { toast } from 'sonner'

import { AudiencePicker, useAudienceDraft } from '@/components/learn/AudiencePicker'
import { AttemptView, ResultView } from '@/components/learn/lesson/QuizRunner'
import { QueryError } from '@/components/QueryError'
import { ActionRow } from '@/components/ui/ActionRow'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { FilterChip } from '@/components/ui/FilterChip'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SegmentGroup, type SegmentOption } from '@/components/ui/SegmentGroup'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import {
  CAMPAIGN_STATUS_LABEL,
  learnApi,
  QUIZ_QUESTION_TYPE_LABEL,
  type AssessmentCampaign,
  type AssessmentReportRow,
  type QuizAttempt,
  type QuizManage,
  type QuizQuestionDraft,
} from '@/lib/learn'
import { nbsp, plural } from '@/lib/typography'

import {
  describeCampaignDeletion,
  resolveAssessmentView,
  type AssessmentView,
} from '@/lib/assessments'
import {
  DISCARD_QUIZ_CONFIRM,
  quizDraftDirty,
  quizSnapshot,
  type QuizDraftSnapshot,
} from '@/lib/quizDraft'

import { QuestionDialog } from './QuizBuilder'

/**
 * Аттестации (Ф8) по макету «Урок — редизайн» (route assess): два среза
 * «Мои / Отчёт» (`SegmentGroup`), карточки кампаний сотрудника (идущая —
 * амбер-рамка, закрытая — `--hair`), «Начать аттестацию» уводит в
 * ПОЛНОЭКРАННЫЙ прогон (вместо inline-попытки в карточке), отчёт — «Прошли:
 * N из M» + полоса + таблица со статусами (цвет только у крайних исходов:
 * сдана — зелёный, не сдана — красный). Управление кампаниями (только
 * hub-admin, ОС 2026-08-10) — третий срез «Кампании» с теми же примитивами;
 * review открытых ответов остаётся publisher'ам в «Управлении».
 */

const REPORT_STATUS_LABEL: Record<AssessmentReportRow['status'], string> = {
  not_started: 'не начинал(а)',
  in_progress: 'в процессе',
  pending_review: 'на проверке',
  passed: 'сдана',
  failed: 'не сдана',
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

function useAssessments() {
  return useQuery({ queryKey: ['learn-assessments'], queryFn: learnApi.assessments })
}

function useCampaignMutation<TArgs>(fn: (args: TArgs) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    meta: { suppressGlobalError: true },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['learn-assessments'] }),
    onError: (e) => toast.error('Не получилось', { description: extractErrorDetail(e) }),
  })
}

/** Ряд действий: 48px на телефоне, 36px в плотной ленте десктопа. */
const ACTION_BTN =
  'h-12 rounded-xl px-5 text-[15px] lg:h-9 lg:rounded-[10px] lg:px-3.5 lg:text-[13px]'
const GHOST_BTN = cn(ACTION_BTN, 'bg-transparent')

// Псевдоним, а не второй список: разъедься они — вкладка и её дефолт
// начали бы понимать разные наборы.
type View = AssessmentView

// ─── Карточка сотрудника ─────────────────────────────────────────────────────

function stateLabel(campaign: AssessmentCampaign): string {
  const s = campaign.my_state
  if (!s) return ''
  if (s.pending_review) return 'На проверке'
  if (s.passed) return `Сдана${s.best_score_pct !== null ? ` · ${s.best_score_pct}%` : ''}`
  if (s.active_attempt_id) return 'В процессе'
  if (s.attempts_used > 0 && !s.can_start)
    return `Не сдана${s.best_score_pct !== null ? ` · ${s.best_score_pct}%` : ''} — попытки исчерпаны`
  if (s.attempts_used > 0) return `Не сдана${s.best_score_pct !== null ? ` · ${s.best_score_pct}%` : ''}`
  return 'Не начата'
}

function EmployeeCampaignCard({
  campaign,
  onStart,
  starting,
}: {
  campaign: AssessmentCampaign
  onStart: () => void
  starting: boolean
}) {
  const state = campaign.my_state
  if (!state) return null
  const active = campaign.status === 'active'
  const deadline = campaign.ends_at
    ? active
      ? `до ${formatDay(campaign.ends_at)}`
      : `закрыта ${formatDay(campaign.ends_at)}`
    : null
  const meta = nbsp(
    `${plural(campaign.question_count, 'вопрос', 'вопроса', 'вопросов')} · ${stateLabel(campaign)}`,
  )

  return (
    <article
      className={cn(
        'flex flex-col gap-[9px] rounded-[14px] border bg-tint p-3.5 lg:p-4',
        active ? 'border-amber/45' : 'border-hair',
      )}
    >
      <div className="flex flex-wrap items-center gap-2 lg:gap-2.5">
        <Badge variant={active ? 'default' : 'secondary'} className={!active ? 'text-text' : undefined}>
          {CAMPAIGN_STATUS_LABEL[campaign.status]}
        </Badge>
        {deadline && <span className="text-[13px] text-text2 lg:text-[14px]">{deadline}</span>}
      </div>
      <div className="lg:flex lg:flex-wrap lg:items-center lg:justify-between lg:gap-3.5">
        <div className="min-w-0">
          <p className="text-[17px] font-semibold leading-[1.3] text-text [text-wrap:pretty] lg:text-[19px]">
            {campaign.title}
          </p>
          <p className="mt-1 text-[15px] text-text2">{meta}</p>
          {campaign.description && (
            <p className="mt-1.5 text-[14px] leading-[1.5] text-text2 [text-wrap:pretty]">{campaign.description}</p>
          )}
        </div>
        {active && state.can_start && (
          <Button
            className="mt-1 h-12 w-full rounded-xl text-[15px] lg:mt-0 lg:h-10 lg:w-auto lg:shrink-0 lg:rounded-[10px] lg:px-[18px]"
            disabled={starting}
            onClick={onStart}
          >
            {state.active_attempt_id ? 'Продолжить аттестацию' : 'Начать аттестацию'}
          </Button>
        )}
      </div>
    </article>
  )
}

/**
 * Полноэкранный прогон аттестации: попытка и результат поверх страницы,
 * с возвратом «Аттестации». Снапшот попытки и проверка — движок Ф3b.
 */
function FullscreenRunner({
  campaign,
  attempt,
  onClose,
}: {
  campaign: AssessmentCampaign
  attempt: QuizAttempt
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [finished, setFinished] = useState<QuizAttempt | null>(null)
  const quiz = campaign.my_state!
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [])
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={campaign.title}
      className="fixed inset-0 z-50 flex flex-col overflow-y-auto bg-bg"
      // Вырез статус-бара — свой: этот слой живёт вне мобильного <main>, которому отступ раздаёт Shell.
      style={{ paddingTop: 'var(--safe-top, 0px)' }}
    >
      <header className="sticky top-0 z-10 flex items-center gap-2 border-b border-hair bg-bg-alt px-3 py-2 lg:px-6">
        <button
          type="button"
          onClick={onClose}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-[15px] font-medium text-text2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
        >
          <ArrowLeft className="h-[18px] w-[18px]" /> Аттестации
        </button>
        <span className="min-w-0 flex-1 truncate text-center text-[14px] font-semibold text-text">
          {campaign.title}
        </span>
        <span className="w-[112px] shrink-0" aria-hidden />
      </header>
      <div className="mx-auto w-full max-w-[720px] px-4 py-5 lg:px-8 lg:py-8">
        {finished ? (
          <ResultView
            attempt={finished}
            quiz={quiz}
            canRetry={false}
            onRetry={() => undefined}
            onExit={onClose}
          />
        ) : (
          <AttemptView
            attempt={attempt}
            quiz={quiz}
            onExit={onClose}
            onFinished={(a) => {
              setFinished(a)
              void qc.invalidateQueries({ queryKey: ['learn-assessments'] })
            }}
          />
        )}
      </div>
    </div>,
    document.body,
  )
}

// ─── Отчёт ───────────────────────────────────────────────────────────────────

function ReportStatusBadge({ status }: { status: AssessmentReportRow['status'] }) {
  // Цвет только у крайних исходов — иначе отчёт на 30 строк становится радугой.
  return (
    <span
      className={cn(
        'inline-flex h-[22px] items-center rounded-md px-2 text-[12px] font-semibold',
        status === 'passed'
          ? 'bg-green-deep text-bg'
          : status === 'failed'
            ? 'bg-red text-bg'
            : 'bg-surface text-text',
      )}
    >
      {REPORT_STATUS_LABEL[status]}
    </span>
  )
}

function ReportView({ campaigns }: { campaigns: AssessmentCampaign[] }) {
  const [selected, setSelected] = useState<string | null>(campaigns[0]?.id ?? null)
  const campaign = campaigns.find((c) => c.id === selected) ?? campaigns[0] ?? null
  const report = useQuery({
    queryKey: ['learn-assessment-report', campaign?.id],
    queryFn: () => learnApi.assessmentReport(campaign!.id),
    enabled: campaign !== null,
  })
  if (campaign === null) {
    return (
      <EmptyState
        layout="card"
        icon={<BadgeCheck className="h-7 w-7" />}
        title="Отчитываться пока не о чем"
        text="Отчёт появится, когда будет запущена хотя бы одна кампания аттестации."
      />
    )
  }
  const rows = report.data?.rows ?? []
  const passed = rows.filter((r) => r.status === 'passed').length
  const pct = rows.length > 0 ? Math.round((passed / rows.length) * 100) : 0
  const deadline = campaign.ends_at ? ` · до ${formatDay(campaign.ends_at)}` : ''

  return (
    <div className="flex flex-col gap-3.5 lg:gap-4">
      {campaigns.length > 1 && (
        <div className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none] lg:mx-0 lg:flex-wrap lg:px-0">
          {campaigns.map((c) => (
            <FilterChip key={c.id} size="md" active={c.id === campaign.id} onClick={() => setSelected(c.id)}>
              {c.title}
            </FilterChip>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center lg:justify-between lg:gap-3.5">
        <div>
          <p className="text-[15px] font-semibold text-text lg:text-[19px]">{campaign.title}</p>
          <p className="mt-1 text-[14px] text-text2 lg:text-[15px]">
            {report.data ? nbsp(`Прошли: ${passed} из ${rows.length}`) : 'Считаем…'}
            <span className="hidden lg:inline">{deadline}</span>
          </p>
        </div>
        <span className="block h-1.5 w-full rounded-[3px] bg-surface lg:w-[220px]">
          <span className="block h-1.5 rounded-[3px] bg-amber transition-[width]" style={{ width: `${pct}%` }} />
        </span>
      </div>

      {report.isLoading && <SkeletonRows rows={5} />}
      {report.isError && <QueryError onRetry={() => void report.refetch()} />}
      {report.data && rows.length === 0 && (
        <p className="text-[14px] text-text2">В аудитории кампании пока никого нет.</p>
      )}
      {rows.length > 0 && (
        <div className="overflow-hidden rounded-[14px] border border-hair bg-tint">
          <div className="hidden grid-cols-[minmax(0,1fr)_130px_72px_116px] items-center gap-3 bg-surface px-3.5 py-2.5 text-[12px] font-bold uppercase tracking-[0.07em] text-text2 lg:grid">
            <span>Сотрудник</span>
            <span>Состояние</span>
            <span>Балл</span>
            <span>Завершено</span>
          </div>
          {rows.map((row, i) => (
            <div
              key={row.profile_id}
              className={cn(
                'flex items-center gap-2.5 px-3.5 py-[11px] lg:grid lg:grid-cols-[minmax(0,1fr)_130px_72px_116px] lg:gap-3',
                i > 0 ? 'border-t border-hair' : 'lg:border-t lg:border-hair',
              )}
            >
              <span className="min-w-0 flex-1 lg:flex-none">
                <span className="block truncate text-[15px] font-semibold leading-[1.3] text-text lg:text-[16px]">
                  {row.full_name}
                </span>
                <span className="mt-[3px] block text-[13px] text-text2 lg:hidden">
                  {row.finished_at ? formatDay(row.finished_at) : '—'}
                </span>
              </span>
              <span className="order-last shrink-0 lg:order-none">
                <ReportStatusBadge status={row.status} />
              </span>
              <span className="shrink-0 font-display text-[14px] font-bold tabular-nums text-text lg:text-[15px]">
                {row.score_pct !== null ? `${row.score_pct}%` : '—'}
              </span>
              <span className="hidden text-[14px] text-text2 lg:block">
                {row.finished_at ? formatDay(row.finished_at) : '—'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Управление кампаниями (hub-admin) ───────────────────────────────────────

function ManagerCampaignCard({ campaign }: { campaign: AssessmentCampaign }) {
  const [questionsOpen, setQuestionsOpen] = useState(false)
  const [audienceOpen, setAudienceOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const activate = useCampaignMutation(() => learnApi.activateAssessment(campaign.id))
  const close = useCampaignMutation(() => learnApi.closeAssessment(campaign.id))
  const active = campaign.status === 'active'

  return (
    <article
      className={cn(
        'flex flex-col gap-[9px] rounded-[14px] border bg-tint p-3.5 lg:p-4',
        active ? 'border-amber/45' : 'border-hair',
      )}
    >
      <div className="flex flex-wrap items-center gap-2 lg:gap-2.5">
        <Badge variant={active ? 'default' : 'secondary'} className={!active ? 'text-text' : undefined}>
          {CAMPAIGN_STATUS_LABEL[campaign.status]}
        </Badge>
        {campaign.ends_at && (
          <span className="text-[13px] text-text2 lg:text-[14px]">
            {active ? 'до' : 'закрыта'} {formatDay(campaign.ends_at)}
          </span>
        )}
      </div>
      <div>
        <p className="text-[17px] font-semibold leading-[1.3] text-text lg:text-[19px]">{campaign.title}</p>
        <p className="mt-1 text-[15px] text-text2">
          {nbsp(
            `${plural(campaign.question_count, 'вопрос', 'вопроса', 'вопросов')} · прошли ${campaign.completed_count} из ${campaign.audience_size}`,
          )}
        </p>
      </div>
      <ActionRow className="mt-0">
        <Button variant="secondary" className={GHOST_BTN} onClick={() => setQuestionsOpen(true)}>
          <Pencil className="h-4 w-4" /> Вопросы
        </Button>
        <Button variant="secondary" className={GHOST_BTN} onClick={() => setAudienceOpen(true)}>
          <Users className="h-4 w-4" /> Аудитория
        </Button>
        {campaign.status === 'draft' && (
          <Button
            className={ACTION_BTN}
            disabled={activate.isPending}
            onClick={() =>
              void activate
                .mutateAsync(undefined as never)
                .then(() => toast.success('Аттестация запущена — аудитория уведомлена'))
            }
          >
            Запустить
          </Button>
        )}
        {/* Удаление — у черновика и у завершённой. Запущенную сервер не отдаёт
            (409): у людей она сейчас на экране, сначала «Закрыть кампанию». */}
        {campaign.status !== 'active' && (
          <Button
            variant="secondary"
            className={cn(GHOST_BTN, 'text-red')}
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 className="h-4 w-4" /> Удалить
          </Button>
        )}
        {active && (
          <Button
            variant="secondary"
            className={cn(GHOST_BTN, 'text-red')}
            disabled={close.isPending}
            onClick={() => void close.mutateAsync(undefined as never)}
          >
            Закрыть кампанию
          </Button>
        )}
      </ActionRow>

      {questionsOpen && <CampaignQuizDialog campaign={campaign} onClose={() => setQuestionsOpen(false)} />}
      {audienceOpen && <CampaignAudienceDialog campaign={campaign} onClose={() => setAudienceOpen(false)} />}
      {deleteOpen && <DeleteCampaignDialog campaign={campaign} onClose={() => setDeleteOpen(false)} />}
    </article>
  )
}

function DeleteCampaignDialog({ campaign, onClose }: { campaign: AssessmentCampaign; onClose: () => void }) {
  const remove = useCampaignMutation(() => learnApi.deleteAssessment(campaign.id))
  // Цена удаления считается по данным кампании, а не пишется общим «вы
  // уверены?»: у завершённой она уносит попытки сотрудников, и об этом надо
  // сказать числом.
  const loss = describeCampaignDeletion(campaign)
  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={`Удалить «${campaign.title}»?`}
      description="Восстановить кампанию будет нельзя. Запущенную сначала закрывают."
      desktopWidth={440}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={remove.isPending}>
            Отмена
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => void remove.mutateAsync(undefined as never).then(onClose)}
          >
            {loss.losesResults ? 'Удалить с результатами' : 'Удалить'}
          </Button>
        </>
      }
    >
      <p
        className={cn(
          'm-0 rounded-xl border border-hair p-3 text-sm',
          // Карточка нейтральная даже когда уходят результаты: красный в
          // системе — просрочка и ошибка, а удаление это не ошибка. Опасность
          // несёт кнопка и само число.
          'bg-tint text-text',
        )}
      >
        {loss.summary}
      </p>
    </ResponsiveDialog>
  )
}

function CampaignQuizDialog({ campaign, onClose }: { campaign: AssessmentCampaign; onClose: () => void }) {
  const quiz = useQuery({
    queryKey: ['learn-assessment-quiz', campaign.id],
    queryFn: () => learnApi.assessmentQuiz(campaign.id),
  })
  const [questions, setQuestions] = useState<QuizQuestionDraft[]>([])
  const [passScore, setPassScore] = useState(80)
  const [attemptsLimit, setAttemptsLimit] = useState<string>('1')
  const [editIndex, setEditIndex] = useState<number | 'new' | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [seeded, setSeeded] = useState(false)
  const qc = useQueryClient()
  // Импорт вопросов ручка отдаёт только администратору
  // (`require_content_role(..., "admin")`), поэтому publisher, нажав кнопку,
  // получал 403 после выбора урока — то есть в конце пути, а не в начале.
  const canImport = useMe().data?.hub_role === 'admin'
  // Снимок того, с чего человек начал. Сравниваем именно с ним, а не с
  // `quiz.data`: если коллега сохранит свой набор, пока диалог открыт, это не
  // повод объявлять работу этого человека изменённой.
  const seededRef = useRef<QuizDraftSnapshot | null>(null)

  // Засеваем РОВНО ОДИН РАЗ, по образцу AudiencePicker.
  //
  // Инцидент 26.08: сотрудница набирала вопросы аттестации, переключалась в
  // другое окно за текстом — и на возврате всё исчезало «в секунду». Причина
  // была здесь: `refetchOnWindowFocus: true` при `staleTime` 30 с даёт рефетч
  // на каждый возврат в окно, ответ приходит НОВЫМ объектом, эффект срабатывал
  // на смену ссылки и затирал локальный черновик серверным списком — а он
  // пустой, пока не нажата «Сохранить». Ни одного запроса на запись при этом
  // не было: вопросы жили только во вкладке.
  //
  // Пересев по изменившимся данным здесь не нужен вовсе: диалог открывают,
  // правят и закрывают, а сохранение — PUT, заменяющий набор целиком.
  //
  // Пересев вынесен функцией: её зовёт и первичный сев, и импорт вопросов.
  // Разъехаться им нельзя — импорт, не обновивший `seededRef`, поднимает
  // ложное «выйти без сохранения?».
  const applyQuiz = useCallback((data: QuizManage) => {
    const snapshot = quizSnapshot(data)
    setPassScore(snapshot.passScore)
    setAttemptsLimit(snapshot.attemptsLimit)
    setQuestions(snapshot.questions)
    seededRef.current = snapshot
  }, [])

  useEffect(() => {
    if (seeded || !quiz.data) return
    applyQuiz(quiz.data)
    setSeeded(true)
  }, [seeded, quiz.data, applyQuiz])

  // Перехват на ОДНОМ месте: `onOpenChange` у ResponsiveDialog срабатывает и на
  // крестик, и на Escape, и на клик мимо — а «Отмена» зовёт тот же путь.
  const closeGuarded = () => {
    const dirty = quizDraftDirty(
      { passScore, attemptsLimit, questions },
      seededRef.current,
    )
    if (dirty && !window.confirm(DISCARD_QUIZ_CONFIRM)) return
    onClose()
  }

  const persist = () =>
    learnApi.upsertAssessmentQuiz(campaign.id, {
      title: campaign.title,
      description: campaign.description,
      status: campaign.status === 'active' ? 'published' : 'draft',
      pass_score_pct: passScore,
      attempts_limit: attemptsLimit.trim() === '' ? null : Number(attemptsLimit),
      shuffle_questions: true,
      shuffle_options: true,
      show_correct_answers: false,
      is_required: false,
      questions,
    })
  const save = useCampaignMutation(persist)

  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && closeGuarded()}
      title={`Вопросы: ${campaign.title}`}
      description="Порог и лимит попыток действуют на всю кампанию; вопросы можно добавить вручную или импортом из теста урока."
      desktopWidth={640}
      footer={
        <>
          <Button variant="secondary" onClick={closeGuarded}>
            Отмена
          </Button>
          <Button
            disabled={save.isPending}
            onClick={() =>
              void save.mutateAsync(undefined as never).then(() => {
                toast.success('Сохранено')
                onClose()
              })
            }
          >
            Сохранить
          </Button>
        </>
      }
    >
      {quiz.isLoading && <SkeletonRows rows={3} />}
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ac-pass">Порог сдачи, %</Label>
          <Input
            id="ac-pass"
            type="number"
            min={1}
            max={100}
            value={passScore}
            onChange={(e) => setPassScore(Number(e.target.value) || 80)}
            className="h-12 text-[15px] lg:h-11"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ac-attempts">Лимит попыток (пусто = ∞)</Label>
          <Input
            id="ac-attempts"
            type="number"
            min={1}
            max={50}
            value={attemptsLimit}
            onChange={(e) => setAttemptsLimit(e.target.value)}
            className="h-12 text-[15px] lg:h-11"
          />
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        {questions.map((q, i) => (
          <div
            key={i}
            className="flex min-h-12 items-center gap-2 rounded-[10px] border border-hair bg-surface px-2.5 py-1.5 text-[14px]"
          >
            <span className="w-5 shrink-0 text-center text-[12px] text-text2">{i + 1}</span>
            <span className="min-w-0 flex-1 truncate text-text">{q.prompt}</span>
            <span className="hidden shrink-0 text-[12px] text-text2 sm:inline">
              {QUIZ_QUESTION_TYPE_LABEL[q.qtype]} · {q.points} б.
            </span>
            <button
              type="button"
              title="Редактировать"
              aria-label="Редактировать вопрос"
              onClick={() => setEditIndex(i)}
              className="flex h-9 w-9 items-center justify-center rounded-md text-text2 hover:text-text"
            >
              <Pencil className="h-4 w-4" />
            </button>
            <button
              type="button"
              title="Убрать"
              aria-label="Убрать вопрос"
              onClick={() => setQuestions((prev) => prev.filter((_, j) => j !== i))}
              className="flex h-9 w-9 items-center justify-center rounded-md text-text2 hover:text-red"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}
        {questions.length === 0 && !quiz.isLoading && (
          <p className="py-2 text-center text-[14px] text-text2">
            {canImport
              ? 'Добавьте вопросы или импортируйте из тестов уроков.'
              : 'Добавьте вопросы аттестации.'}
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" className="bg-transparent" onClick={() => setEditIndex('new')}>
          <Plus className="h-4 w-4" /> Вопрос
        </Button>
        {canImport && (
          <Button
            variant="secondary"
            className="bg-transparent"
            onClick={() => setImportOpen(true)}
          >
            <Import className="h-4 w-4" /> Импорт из теста урока
          </Button>
        )}
      </div>

      {editIndex !== null && (
        <QuestionDialog
          initial={editIndex === 'new' ? null : (questions[editIndex] ?? null)}
          onClose={() => setEditIndex(null)}
          onSave={(draft) => {
            setQuestions((prev) =>
              editIndex === 'new' ? [...prev, draft] : prev.map((q, i) => (i === editIndex ? draft : q)),
            )
            setEditIndex(null)
          }}
        />
      )}
      {importOpen && (
        <ImportQuestionsDialog
          campaign={campaign}
          beforeImport={persist}
          onClose={() => setImportOpen(false)}
          onImported={(fresh) => {
            setImportOpen(false)
            // Берём набор ИЗ ОТВЕТА импорта, а не из рефетча: раньше здесь был
            // `quiz.refetch()`, но пересев стоит под сторожем `seeded`, и
            // импортированные вопросы на экран не попадали. Дальше «Сохранить»
            // слал PUT со старым набором, а ручка кампании — replace: строки
            // импортированных вопросов физически удалялись.
            applyQuiz(fresh)
            // Кэш обновляем ЗДЕСЬ же: без этого возврат в окно поднял бы
            // рефетч, а `staleTime` 30 с успел бы отдать устаревший ответ.
            qc.setQueryData(['learn-assessment-quiz', campaign.id], fresh)
          }}
        />
      )}
    </ResponsiveDialog>
  )
}

function ImportQuestionsDialog({
  campaign,
  beforeImport,
  onClose,
  onImported,
}: {
  campaign: AssessmentCampaign
  // Сохраняет несохранённые локальные вопросы: импорт добавляет вопросы НА
  // СЕРВЕРЕ и возвращает набор целиком, поэтому несохранённое иначе потеряется.
  beforeImport: () => Promise<unknown>
  onClose: () => void
  onImported: (fresh: QuizManage) => void
}) {
  const courses = useQuery({ queryKey: ['learn-courses', true], queryFn: () => learnApi.courses(true) })
  const [busy, setBusy] = useState(false)

  const importFrom = async (lessonId: string, title: string) => {
    setBusy(true)
    try {
      await beforeImport()
      const quiz = await learnApi.lessonQuizManage(lessonId)
      if (!quiz) {
        toast.error(`У урока «${title}» нет теста`)
        return
      }
      const fresh = await learnApi.importAssessmentQuestions(campaign.id, quiz.id)
      toast.success(
        `Импортировано ${plural(quiz.questions.length, 'вопрос', 'вопроса', 'вопросов')}`,
      )
      onImported(fresh)
    } catch (e) {
      toast.error('Импорт не удался', { description: extractErrorDetail(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title="Импорт вопросов"
      description="Выберите урок — вопросы его теста скопируются в аттестацию."
    >
      <div className="flex flex-col gap-3">
        {(courses.data?.items ?? []).map((course) => (
          <CourseLessonPicker
            key={course.id}
            courseId={course.id}
            courseTitle={course.title}
            disabled={busy}
            onPick={importFrom}
          />
        ))}
        {courses.isLoading && <SkeletonRows rows={3} />}
      </div>
    </ResponsiveDialog>
  )
}

function CourseLessonPicker({
  courseId,
  courseTitle,
  disabled,
  onPick,
}: {
  courseId: string
  courseTitle: string
  disabled: boolean
  onPick: (lessonId: string, title: string) => void
}) {
  const course = useQuery({
    queryKey: ['learn-course', courseId],
    queryFn: () => learnApi.course(courseId),
  })
  const lessons = course.data?.lessons ?? []
  if (!lessons.length) return null
  return (
    <div>
      <p className="mb-1.5 text-[12px] font-bold uppercase tracking-[0.08em] text-text2">{courseTitle}</p>
      <div className="flex flex-col gap-1.5">
        {lessons.map((lesson) => (
          <button
            key={lesson.id}
            type="button"
            disabled={disabled}
            onClick={() => onPick(lesson.id, lesson.title)}
            className="flex min-h-12 w-full items-center gap-2 rounded-[10px] border border-hair px-3.5 text-left text-[15px] text-text hover:border-amber/50 disabled:opacity-50 lg:min-h-11"
          >
            <span className="min-w-0 flex-1 truncate">{lesson.title}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function CampaignAudienceDialog({ campaign, onClose }: { campaign: AssessmentCampaign; onClose: () => void }) {
  const audience = useAudienceDraft(campaign.audience_id)
  const { value, setValue } = audience
  const save = useCampaignMutation(() => learnApi.setAssessmentAudience(campaign.id, value))
  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={`Кто проходит «${campaign.title}»`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            disabled={save.isPending || !audience.ready}
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

function CreateCampaignDialog({ onClose }: { onClose: () => void }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [endsAt, setEndsAt] = useState('')
  const create = useCampaignMutation(() =>
    learnApi.createAssessment({
      title: title.trim(),
      description: description.trim() || null,
      ends_at: endsAt ? new Date(`${endsAt}T23:59`).toISOString() : null,
    }),
  )
  const submit = () => {
    if (!title.trim()) return
    void create.mutateAsync(undefined as never).then(() => {
      toast.success('Кампания создана — добавьте вопросы и запустите')
      onClose()
    })
  }
  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title="Новая аттестация"
      description="Кампания создаётся черновиком: добавьте вопросы, задайте аудиторию и запустите — участники получат уведомление с дедлайном."
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="button" onClick={submit} disabled={!title.trim() || create.isPending}>
            Создать
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
          <Label htmlFor="camp-title">Название</Label>
          <Input
            id="camp-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Годовая аттестация бариста"
            maxLength={255}
            autoFocus
            className="h-12 text-[15px] lg:h-11"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="camp-desc">Описание</Label>
          <textarea
            id="camp-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="flex w-full rounded-[10px] border border-glass-border bg-surface px-3.5 py-2.5 text-[15px] text-text focus-visible:border-amber focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="camp-ends">Дедлайн (необязательно)</Label>
          <Input
            id="camp-ends"
            type="date"
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
            className="h-12 text-[15px] lg:h-11"
          />
        </div>
      </form>
    </ResponsiveDialog>
  )
}

// ─── Страница ────────────────────────────────────────────────────────────────

export function LearnAssessmentsPage() {
  const isDesktop = useIsDesktop()
  const me = useMe()
  const data = useAssessments()
  // null = «человек ещё не выбирал»: вкладку по умолчанию считает
  // `resolveAssessmentView` по роли, а не эффект после приезда `me`.
  const [view, setView] = useState<View | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [running, setRunning] = useState<{ campaign: AssessmentCampaign; attempt: QuizAttempt } | null>(
    null,
  )

  const items = useMemo(() => data.data ?? [], [data.data])
  const isAdmin = me.data?.hub_role === 'admin'
  // Отчёт отдаёт сервер publisher'ам и руководителям магазинов (ТУ/франчайзи);
  // hub-admin проходит как publisher.
  const canReport =
    isAdmin ||
    me.data?.profile?.content_role === 'publisher' ||
    me.data?.profile?.org_role === 'tu' ||
    me.data?.profile?.org_role === 'franchisee_owner'

  const mine = useMemo(() => items.filter((c) => c.my_state !== null), [items])
  const options = useMemo(() => {
    const out: SegmentOption<View>[] = [{ value: 'my', label: 'Мои' }]
    if (canReport) out.push({ value: 'report', label: 'Отчёт' })
    if (isAdmin) out.push({ value: 'manage', label: 'Кампании' })
    return out
  }, [canReport, isAdmin])
  const effectiveView = resolveAssessmentView(
    view,
    options.map((o) => o.value),
    isAdmin,
  )

  const start = useMutation({
    mutationFn: (campaign: AssessmentCampaign) =>
      learnApi.startQuizAttempt(campaign.my_state!.id).then((attempt) => ({ campaign, attempt })),
    meta: { suppressGlobalError: true },
    onSuccess: setRunning,
    onError: (e) => toast.error('Не удалось начать', { description: extractErrorDetail(e) }),
  })

  return (
    <div className="mx-auto max-w-[860px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
      <header className="flex flex-col gap-4 lg:flex-row lg:flex-wrap lg:items-end lg:justify-between lg:gap-3.5">
        <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
          Аттестации
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          {options.length > 1 && (
            <SegmentGroup
              ariaLabel="Вид"
              options={options}
              value={effectiveView}
              onChange={setView}
              size={isDesktop ? 'md' : 'lg'}
            />
          )}
          {isAdmin && effectiveView === 'manage' && (
            <>
              <span className="flex-1 lg:hidden" />
              <Button
                onClick={() => setCreateOpen(true)}
                className="h-12 rounded-xl px-5 text-[15px] lg:h-9 lg:rounded-[10px] lg:px-3.5 lg:text-[13px]"
              >
                <Plus className="h-4 w-4" /> Аттестация
              </Button>
            </>
          )}
        </div>
      </header>

      <div className="mt-4 flex flex-col gap-3 lg:mt-[22px]">
        {data.isLoading && <SkeletonRows rows={3} />}
        {data.isError && <QueryError onRetry={() => void data.refetch()} />}

        {data.data && effectiveView === 'my' && (
          <>
            {mine.length === 0 && (
              <EmptyState
                layout="card"
                icon={<BadgeCheck className="h-7 w-7" />}
                title="Назначенных аттестаций нет"
                text="Когда руководитель запустит кампанию для вашей должности или магазина, она появится здесь с дедлайном."
              />
            )}
            {mine.map((campaign) => (
              <EmployeeCampaignCard
                key={campaign.id}
                campaign={campaign}
                starting={start.isPending && start.variables?.id === campaign.id}
                onStart={() => start.mutate(campaign)}
              />
            ))}
          </>
        )}

        {data.data && effectiveView === 'report' && (
          <ReportView campaigns={items.filter((c) => c.status !== 'draft')} />
        )}

        {data.data && effectiveView === 'manage' && (
          <>
            {items.length === 0 && (
              <EmptyState
                layout="card"
                icon={<BadgeCheck className="h-7 w-7" />}
                title="Кампаний пока нет"
                text="Создайте аттестацию, добавьте вопросы (можно импортом из тестов уроков) и запустите — аудитория получит уведомление."
                cta="Новая аттестация"
                onCta={() => setCreateOpen(true)}
              />
            )}
            {items.map((campaign) => (
              <ManagerCampaignCard key={campaign.id} campaign={campaign} />
            ))}
          </>
        )}
      </div>

      {createOpen && <CreateCampaignDialog onClose={() => setCreateOpen(false)} />}
      {running && (
        <FullscreenRunner
          campaign={running.campaign}
          attempt={running.attempt}
          onClose={() => setRunning(null)}
        />
      )}
    </div>
  )
}
