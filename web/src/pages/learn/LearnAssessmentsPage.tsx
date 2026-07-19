import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BadgeCheck,
  CalendarClock,
  Check,
  Clock,
  Import,
  Pencil,
  Play,
  Plus,
  Table2,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { AudiencePicker, type AudienceValue } from '@/components/learn/AudiencePicker'
import { AttemptView, ResultView } from '@/components/learn/lesson/QuizRunner'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Badge } from '@/components/ui/Badge'
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
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import {
  CAMPAIGN_STATUS_LABEL,
  learnApi,
  QUIZ_QUESTION_TYPE_LABEL,
  type AssessmentCampaign,
  type QuizAttempt,
  type QuizQuestionDraft,
} from '@/lib/learn'

import { QuestionDialog } from './QuizBuilder'

/**
 * Аттестации (Ф8): сотрудник проходит назначенные кампании (движок тестов
 * Ф3b — попытки/снапшоты/ревью); publisher управляет кампаниями, вопросами
 * (в т.ч. импорт из тестов уроков) и смотрит отчёт.
 */

const REPORT_STATUS_LABEL: Record<string, string> = {
  not_started: 'не начинал(а)',
  in_progress: 'в процессе',
  pending_review: 'на проверке',
  passed: 'сдана',
  failed: 'не сдана',
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

// ─── Карточка сотрудника ─────────────────────────────────────────────────────

function EmployeeCampaignCard({ campaign }: { campaign: AssessmentCampaign }) {
  const qc = useQueryClient()
  const [attempt, setAttempt] = useState<QuizAttempt | null>(null)
  const [finished, setFinished] = useState<QuizAttempt | null>(null)
  const state = campaign.my_state

  const start = useMutation({
    mutationFn: () => learnApi.startQuizAttempt(campaign.my_state!.id),
    meta: { suppressGlobalError: true },
    onSuccess: setAttempt,
    onError: (e) =>
      toast.error('Не удалось начать', { description: extractErrorDetail(e) }),
  })

  if (!state) return null
  const deadline = campaign.ends_at
    ? new Date(campaign.ends_at).toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'long',
      })
    : null

  return (
    <div className="rounded-xl border border-glass-border bg-glass p-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="default">
          <BadgeCheck className="mr-1 h-3 w-3" /> Аттестация
        </Badge>
        {deadline && (
          <span className="inline-flex items-center gap-1 text-xs text-text3">
            <CalendarClock className="h-3.5 w-3.5" /> до {deadline}
          </span>
        )}
      </div>
      <p className="mt-1.5 text-sm font-medium text-text">{campaign.title}</p>
      {campaign.description && (
        <p className="mt-0.5 text-sm text-text2">{campaign.description}</p>
      )}
      <p className="mt-0.5 text-xs text-text3">
        {campaign.question_count} вопросов · порог {state.pass_score_pct}%
        {state.attempts_limit !== null && ` · попыток: ${state.attempts_used}/${state.attempts_limit}`}
      </p>

      <div className="mt-3">
        {attempt ? (
          <AttemptView
            attempt={attempt}
            onFinished={(a) => {
              setAttempt(null)
              setFinished(a)
              void qc.invalidateQueries({ queryKey: ['learn-assessments'] })
            }}
          />
        ) : finished ? (
          <ResultView
            attempt={finished}
            quiz={state}
            canRetry={false}
            onRetry={() => undefined}
          />
        ) : state.pending_review ? (
          <p className="inline-flex items-center gap-1.5 rounded-lg border border-amber/40 bg-amber/5 px-3 py-2 text-sm text-text2">
            <Clock className="h-4 w-4 text-amber" /> На проверке — дождитесь результата.
          </p>
        ) : state.passed ? (
          <p className="inline-flex items-center gap-1.5 rounded-lg border border-green/50 bg-green/10 px-3 py-2 text-sm text-text">
            <Check className="h-4 w-4 text-green" /> Сдана на {state.best_score_pct}%
          </p>
        ) : state.can_start ? (
          <Button size="sm" disabled={start.isPending} onClick={() => start.mutate()}>
            <Play className="h-4 w-4" />
            {state.active_attempt_id ? 'Продолжить' : 'Пройти аттестацию'}
          </Button>
        ) : (
          <p className="inline-flex items-center gap-1.5 rounded-lg border border-red/40 bg-red/5 px-3 py-2 text-sm text-text2">
            <X className="h-4 w-4 text-red" />
            {state.attempts_used > 0
              ? `Не сдана (${state.best_score_pct ?? 0}%) — попытки исчерпаны`
              : 'Недоступна'}
          </p>
        )}
      </div>
    </div>
  )
}

// ─── Карточка менеджера ──────────────────────────────────────────────────────

function ManagerCampaignCard({ campaign }: { campaign: AssessmentCampaign }) {
  const [questionsOpen, setQuestionsOpen] = useState(false)
  const [audienceOpen, setAudienceOpen] = useState(false)
  const [reportOpen, setReportOpen] = useState(false)

  const activate = useCampaignMutation(() => learnApi.activateAssessment(campaign.id))
  const close = useCampaignMutation(() => learnApi.closeAssessment(campaign.id))
  const remove = useCampaignMutation(() => learnApi.deleteAssessment(campaign.id))

  return (
    <div className="rounded-xl border border-glass-border bg-glass p-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={campaign.status === 'active' ? 'default' : 'secondary'}>
          {CAMPAIGN_STATUS_LABEL[campaign.status]}
        </Badge>
        <span className="text-xs text-text3">
          {campaign.question_count} вопросов · прошли {campaign.completed_count}/
          {campaign.audience_size}
        </span>
      </div>
      <p className="mt-1.5 text-sm font-medium text-text">{campaign.title}</p>

      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => setQuestionsOpen(true)}>
          <Pencil className="h-4 w-4" /> Вопросы
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setAudienceOpen(true)}>
          <Users className="h-4 w-4" /> Аудитория
        </Button>
        {campaign.status === 'draft' && (
          <>
            <Button
              size="sm"
              disabled={activate.isPending}
              onClick={() =>
                void activate
                  .mutateAsync(undefined as never)
                  .then(() => toast.success('Аттестация запущена — аудитория уведомлена'))
              }
            >
              Запустить
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-red"
              disabled={remove.isPending}
              onClick={() => {
                if (!window.confirm(`Удалить «${campaign.title}»?`)) return
                void remove.mutateAsync(undefined as never)
              }}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </>
        )}
        {campaign.status === 'active' && (
          <Button
            size="sm"
            variant="ghost"
            disabled={close.isPending}
            onClick={() => void close.mutateAsync(undefined as never)}
          >
            Закрыть кампанию
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => setReportOpen(true)}>
          <Table2 className="h-4 w-4" /> Отчёт
        </Button>
      </div>

      {questionsOpen && (
        <CampaignQuizDialog campaign={campaign} onClose={() => setQuestionsOpen(false)} />
      )}
      {audienceOpen && (
        <CampaignAudienceDialog campaign={campaign} onClose={() => setAudienceOpen(false)} />
      )}
      {reportOpen && (
        <CampaignReportDialog campaign={campaign} onClose={() => setReportOpen(false)} />
      )}
    </div>
  )
}

function CampaignQuizDialog({
  campaign,
  onClose,
}: {
  campaign: AssessmentCampaign
  onClose: () => void
}) {
  const quiz = useQuery({
    queryKey: ['learn-assessment-quiz', campaign.id],
    queryFn: () => learnApi.assessmentQuiz(campaign.id),
  })
  const [questions, setQuestions] = useState<QuizQuestionDraft[]>([])
  const [passScore, setPassScore] = useState(80)
  const [attemptsLimit, setAttemptsLimit] = useState<string>('1')
  const [editIndex, setEditIndex] = useState<number | 'new' | null>(null)
  const [importOpen, setImportOpen] = useState(false)

  useEffect(() => {
    if (quiz.data) {
      setPassScore(quiz.data.pass_score_pct)
      setAttemptsLimit(quiz.data.attempts_limit === null ? '' : String(quiz.data.attempts_limit))
      setQuestions(
        quiz.data.questions.map((q) => ({
          qtype: q.qtype,
          prompt: q.prompt,
          media_id: q.media_id,
          options: q.options,
          answer: q.answer,
          points: q.points,
        })),
      )
    }
  }, [quiz.data])

  const save = useCampaignMutation(() =>
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
    }),
  )

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Вопросы: {campaign.title}</DialogTitle>
        </DialogHeader>
        {quiz.isLoading && <SkeletonRows rows={3} />}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label htmlFor="ac-pass">Порог сдачи, %</Label>
            <Input
              id="ac-pass"
              type="number"
              min={1}
              max={100}
              value={passScore}
              onChange={(e) => setPassScore(Number(e.target.value) || 80)}
            />
          </div>
          <div>
            <Label htmlFor="ac-attempts">Лимит попыток (пусто = ∞)</Label>
            <Input
              id="ac-attempts"
              type="number"
              min={1}
              max={50}
              value={attemptsLimit}
              onChange={(e) => setAttemptsLimit(e.target.value)}
            />
          </div>
        </div>
        <div className="space-y-1.5">
          {questions.map((q, i) => (
            <div
              key={i}
              className="flex items-center gap-2 rounded-md border border-glass-border bg-surface px-2.5 py-1.5 text-sm"
            >
              <span className="w-5 shrink-0 text-center text-xs text-text3">{i + 1}</span>
              <span className="min-w-0 flex-1 truncate text-text">{q.prompt}</span>
              <span className="shrink-0 text-xs text-text3">
                {QUIZ_QUESTION_TYPE_LABEL[q.qtype]} · {q.points} б.
              </span>
              <button
                type="button"
                title="Редактировать"
                onClick={() => setEditIndex(i)}
                className="rounded p-1 text-text3 hover:text-text"
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                type="button"
                title="Убрать"
                onClick={() => setQuestions((prev) => prev.filter((_, j) => j !== i))}
                className="rounded p-1 text-text3 hover:text-red"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
          {questions.length === 0 && !quiz.isLoading && (
            <p className="py-2 text-center text-sm text-text3">
              Добавьте вопросы или импортируйте из тестов уроков.
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => setEditIndex('new')}>
            <Plus className="h-4 w-4" /> Вопрос
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setImportOpen(true)}>
            <Import className="h-4 w-4" /> Импорт из теста урока
          </Button>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
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
        </DialogFooter>

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
        {importOpen && (
          <ImportQuestionsDialog
            campaign={campaign}
            onClose={() => setImportOpen(false)}
            onImported={() => {
              setImportOpen(false)
              void quiz.refetch()
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function ImportQuestionsDialog({
  campaign,
  onClose,
  onImported,
}: {
  campaign: AssessmentCampaign
  onClose: () => void
  onImported: () => void
}) {
  // Список тестов уроков: курсы (manage) → уроки → их квизы дочитываем лениво.
  const courses = useQuery({ queryKey: ['learn-courses', true], queryFn: () => learnApi.courses(true) })
  const [busy, setBusy] = useState(false)

  const importFrom = async (lessonId: string, title: string) => {
    setBusy(true)
    try {
      const quiz = await learnApi.lessonQuizManage(lessonId)
      if (!quiz) {
        toast.error(`У урока «${title}» нет теста`)
        return
      }
      await learnApi.importAssessmentQuestions(campaign.id, quiz.id)
      toast.success('Вопросы импортированы')
      onImported()
    } catch (e) {
      toast.error('Импорт не удался', { description: extractErrorDetail(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Импорт вопросов</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-text3">
          Выберите урок — вопросы его теста скопируются в аттестацию.
        </p>
        <div className="space-y-2">
          {(courses.data?.items ?? []).map((course) => (
            <CourseLessonPicker
              key={course.id}
              courseId={course.id}
              courseTitle={course.title}
              disabled={busy}
              onPick={importFrom}
            />
          ))}
        </div>
      </DialogContent>
    </Dialog>
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
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text3">
        {courseTitle}
      </p>
      <div className="space-y-1">
        {lessons.map((lesson) => (
          <button
            key={lesson.id}
            type="button"
            disabled={disabled}
            onClick={() => onPick(lesson.id, lesson.title)}
            className="flex w-full items-center gap-2 rounded-lg border border-glass-border px-3 py-1.5 text-left text-sm text-text hover:border-amber/50 disabled:opacity-50"
          >
            <span className="min-w-0 flex-1 truncate">{lesson.title}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function CampaignAudienceDialog({
  campaign,
  onClose,
}: {
  campaign: AssessmentCampaign
  onClose: () => void
}) {
  const [value, setValue] = useState<AudienceValue>({
    is_all: campaign.audience_id === null,
    rules: [],
  })
  const save = useCampaignMutation(() =>
    learnApi.setAssessmentAudience(campaign.id, value),
  )
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Кто проходит «{campaign.title}»</DialogTitle>
        </DialogHeader>
        <AudiencePicker value={value} onChange={setValue} />
        <DialogFooter>
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
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

function CampaignReportDialog({
  campaign,
  onClose,
}: {
  campaign: AssessmentCampaign
  onClose: () => void
}) {
  const report = useQuery({
    queryKey: ['learn-assessment-report', campaign.id],
    queryFn: () => learnApi.assessmentReport(campaign.id),
  })
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Отчёт: {campaign.title}</DialogTitle>
        </DialogHeader>
        {report.isLoading && <SkeletonRows rows={4} />}
        {report.data && (
          <div className="overflow-x-auto rounded-lg border border-glass-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-glass-border text-left text-xs text-text3">
                  <th className="px-3 py-2 font-medium">Сотрудник</th>
                  <th className="px-3 py-2 font-medium">Статус</th>
                  <th className="px-3 py-2 text-right font-medium">Балл</th>
                </tr>
              </thead>
              <tbody>
                {report.data.rows.map((row) => (
                  <tr key={row.profile_id} className="border-b border-glass-border/50 last:border-0">
                    <td className="px-3 py-2 text-text">{row.full_name}</td>
                    <td
                      className={cn(
                        'px-3 py-2',
                        row.status === 'passed'
                          ? 'text-green'
                          : row.status === 'failed'
                            ? 'text-red'
                            : 'text-text2',
                      )}
                    >
                      {REPORT_STATUS_LABEL[row.status]}
                    </td>
                    <td className="px-3 py-2 text-right text-text">
                      {row.score_pct !== null ? `${row.score_pct}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ─── Страница ────────────────────────────────────────────────────────────────

export function LearnAssessmentsPage() {
  const isDesktop = useIsDesktop()
  const data = useAssessments()
  const [createOpen, setCreateOpen] = useState(false)

  const items = data.data ?? []

  return (
    <div className="mx-auto max-w-3xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Аттестации" />}
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex items-center justify-between gap-2">
          {isDesktop && (
            <h1 className="font-display text-2xl font-bold text-text">Аттестации</h1>
          )}
          <CreateButton onOpen={() => setCreateOpen(true)} />
        </div>

        {data.isLoading && <SkeletonRows rows={3} />}
        {data.isError && <QueryError onRetry={() => void data.refetch()} />}

        {data.data && items.length === 0 && (
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <BadgeCheck className="mx-auto h-8 w-8 text-text3" />
            <p className="mt-3 text-sm text-text2">Активных аттестаций нет.</p>
          </div>
        )}

        <div className="space-y-3">
          {items.map((campaign) =>
            campaign.my_state !== null ? (
              <EmployeeCampaignCard key={campaign.id} campaign={campaign} />
            ) : (
              <ManagerCampaignCard key={campaign.id} campaign={campaign} />
            ),
          )}
        </div>

        {createOpen && <CreateCampaignDialog onClose={() => setCreateOpen(false)} />}
      </div>
    </div>
  )
}

function CreateButton({ onOpen }: { onOpen: () => void }) {
  // Кнопка видна только тем, кому сервер отдаёт менеджерский список
  // (сотрудникам создание вернёт 403 — кнопку не показываем на всякий).
  const me = useQuery({ queryKey: ['learn-assessments'], queryFn: learnApi.assessments })
  const isManager = (me.data ?? []).some((c) => c.my_state === null)
  const empty = (me.data ?? []).length === 0
  if (!isManager && !empty) return null
  return (
    <Button onClick={onOpen}>
      <Plus className="h-4 w-4" /> Аттестация
    </Button>
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

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    void create.mutateAsync(undefined as never).then(() => {
      toast.success('Кампания создана — добавьте вопросы и запустите')
      onClose()
    })
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Новая аттестация</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 py-3">
            <div>
              <Label htmlFor="camp-title">Название</Label>
              <Input
                id="camp-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Годовая аттестация бариста"
                maxLength={255}
                autoFocus
              />
            </div>
            <div>
              <Label htmlFor="camp-desc">Описание</Label>
              <textarea
                id="camp-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className="flex w-full rounded-lg border border-glass-border bg-glass px-3 py-2 text-sm text-text focus-visible:border-amber focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber"
              />
            </div>
            <div>
              <Label htmlFor="camp-ends">Дедлайн (необязательно)</Label>
              <Input
                id="camp-ends"
                type="date"
                value={endsAt}
                onChange={(e) => setEndsAt(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={!title.trim() || create.isPending}>
              Создать
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
