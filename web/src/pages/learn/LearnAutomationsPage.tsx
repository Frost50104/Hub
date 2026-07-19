import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2, Workflow, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

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
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { Switch } from '@/components/ui/Switch'
import { useCourses, useOrgSnapshot } from '@/hooks/useLearn'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import {
  AUTOMATION_TRIGGER_LABEL,
  learnApi,
  type AutomationRule,
  type AutomationRuleUpsert,
  type AutomationTrigger,
} from '@/lib/learn'

/**
 * Автосценарии (Ф5, ТЗ §22): welcome-правила «новичок → курс с дедлайном».
 * Правило применяется только к профилям, созданным ПОСЛЕ его включения —
 * ретро-назначений ветеранам нет. Джобы исполняет hourly-cron.
 */

const JOB_STATUS_LABEL: Record<string, string> = {
  pending: 'ожидает',
  done: 'выполнено',
  cancelled: 'отменено',
}

export function LearnAutomationsPage() {
  const qc = useQueryClient()
  const rules = useQuery({ queryKey: ['learn-automations'], queryFn: learnApi.automations })
  const [editor, setEditor] = useState<AutomationRule | 'new' | null>(null)
  const [jobsFor, setJobsFor] = useState<AutomationRule | null>(null)

  const remove = useMutation({
    mutationFn: (id: string) => learnApi.deleteAutomation(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['learn-automations'] }),
  })

  return (
    <div className="mx-auto max-w-3xl">
      <MobilePageHeader eyebrow="Обучение" title="Автосценарии" className="lg:hidden" />
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex items-center justify-between gap-2">
          <h1 className="hidden font-display text-2xl font-bold text-text lg:block">
            Автосценарии
          </h1>
          <Button onClick={() => setEditor('new')}>
            <Plus className="h-4 w-4" /> Правило
          </Button>
        </div>
        <p className="text-xs text-text3">
          Правила применяются только к сотрудникам, заведённым после включения —
          массового назначения ветеранам не будет. Проверка — каждый час.
        </p>

        {rules.isLoading && <SkeletonRows rows={3} />}
        {rules.isError && <QueryError onRetry={() => void rules.refetch()} />}

        {rules.data && rules.data.length === 0 && (
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <Workflow className="mx-auto h-8 w-8 text-text3" />
            <p className="mt-3 text-sm text-text2">
              Правил пока нет. Создайте welcome-сценарий для новичков.
            </p>
          </div>
        )}

        {rules.data?.map((rule) => (
          <div
            key={rule.id}
            className={cn(
              'rounded-xl border bg-glass p-4',
              rule.enabled ? 'border-glass-border' : 'border-glass-border opacity-60',
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-text">
                  {rule.title}
                  {!rule.enabled && <Badge variant="secondary">выключено</Badge>}
                </p>
                <p className="mt-0.5 text-xs text-text3">
                  {AUTOMATION_TRIGGER_LABEL[rule.trigger]}
                  {rule.position_ids.length > 0 &&
                    ` (${rule.position_ids.length} должн.)`}{' '}
                  → «{rule.course_title ?? 'курс удалён'}»
                  {rule.due_days ? ` · срок ${rule.due_days} дн.` : ''}
                </p>
                <button
                  type="button"
                  onClick={() => setJobsFor(rule)}
                  className="mt-1 text-xs text-amber hover:opacity-80"
                >
                  назначено: {rule.jobs_done} · в очереди: {rule.jobs_pending}
                </button>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  title="Редактировать"
                  onClick={() => setEditor(rule)}
                  className="rounded p-1.5 text-text3 hover:bg-surface hover:text-text"
                >
                  <Pencil className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  title="Удалить"
                  onClick={() => {
                    if (!window.confirm(`Удалить правило «${rule.title}»?`)) return
                    void remove.mutateAsync(rule.id)
                  }}
                  className="rounded p-1.5 text-text3 hover:bg-surface hover:text-red"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        ))}

        {editor !== null && (
          <RuleEditorDialog
            initial={editor === 'new' ? null : editor}
            onClose={() => setEditor(null)}
          />
        )}
        {jobsFor && <JobsDialog rule={jobsFor} onClose={() => setJobsFor(null)} />}
      </div>
    </div>
  )
}

function RuleEditorDialog({
  initial,
  onClose,
}: {
  initial: AutomationRule | null
  onClose: () => void
}) {
  const qc = useQueryClient()
  const org = useOrgSnapshot()
  const courses = useCourses(true)
  const [title, setTitle] = useState(initial?.title ?? '')
  const [trigger, setTrigger] = useState<AutomationTrigger>(
    initial?.trigger ?? 'profile_activated',
  )
  const [positionIds, setPositionIds] = useState<string[]>(initial?.position_ids ?? [])
  const [courseId, setCourseId] = useState(initial?.course_id ?? '')
  const [dueDays, setDueDays] = useState<string>(String(initial?.due_days ?? 14))
  const [enabled, setEnabled] = useState(initial?.enabled ?? true)

  const save = useMutation({
    mutationFn: () => {
      const body: AutomationRuleUpsert = {
        title: title.trim(),
        trigger,
        position_ids: trigger === 'position_assigned' ? positionIds : [],
        course_id: courseId,
        due_days: dueDays.trim() === '' ? null : Number(dueDays),
        enabled,
      }
      return initial
        ? learnApi.updateAutomation(initial.id, body)
        : learnApi.createAutomation(body)
    },
    meta: { suppressGlobalError: true },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-automations'] })
      toast.success('Правило сохранено')
      onClose()
    },
    onError: (e) =>
      toast.error('Не удалось сохранить', { description: extractErrorDetail(e) }),
  })

  const positions = org.data?.positions.filter((p) => !p.archived_at) ?? []

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{initial ? 'Правило' : 'Новое правило'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2.5">
          <div>
            <Label htmlFor="ar-title">Название</Label>
            <Input
              id="ar-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Welcome для новичков"
              maxLength={255}
            />
          </div>
          <div>
            <Label htmlFor="ar-trigger">Когда срабатывает</Label>
            <Select
              id="ar-trigger"
              value={trigger}
              onChange={(e) => setTrigger(e.target.value as AutomationTrigger)}
            >
              {(Object.keys(AUTOMATION_TRIGGER_LABEL) as AutomationTrigger[]).map((t) => (
                <option key={t} value={t}>
                  {AUTOMATION_TRIGGER_LABEL[t]}
                </option>
              ))}
            </Select>
          </div>
          {trigger === 'position_assigned' && (
            <div>
              <Label>Должности (пусто = любая)</Label>
              <div className="flex flex-wrap gap-1.5">
                {positions.map((p) => {
                  const active = positionIds.includes(p.id)
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() =>
                        setPositionIds((prev) =>
                          active ? prev.filter((id) => id !== p.id) : [...prev, p.id],
                        )
                      }
                      className={cn(
                        'rounded-full border px-3 py-1 text-xs',
                        active
                          ? 'border-amber/60 bg-amber/10 text-amber'
                          : 'border-glass-border text-text2 hover:text-text',
                      )}
                    >
                      {p.name}
                    </button>
                  )
                })}
              </div>
            </div>
          )}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div>
              <Label htmlFor="ar-course">Назначить курс</Label>
              <Select
                id="ar-course"
                value={courseId}
                onChange={(e) => setCourseId(e.target.value)}
              >
                <option value="">— выберите курс —</option>
                {(courses.data?.items ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="ar-due">Срок, дней (пусто = без срока)</Label>
              <Input
                id="ar-due"
                type="number"
                min={1}
                max={365}
                value={dueDays}
                onChange={(e) => setDueDays(e.target.value)}
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-text2">
            <Switch checked={enabled} onCheckedChange={setEnabled} />
            правило включено
          </label>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button
            disabled={!title.trim() || !courseId || save.isPending}
            onClick={() => save.mutate()}
          >
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function JobsDialog({ rule, onClose }: { rule: AutomationRule; onClose: () => void }) {
  const qc = useQueryClient()
  const jobs = useQuery({
    queryKey: ['learn-automation-jobs', rule.id],
    queryFn: () => learnApi.automationJobs(rule.id),
  })
  const cancel = useMutation({
    mutationFn: (jobId: string) => learnApi.cancelAutomationJob(jobId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-automation-jobs', rule.id] })
      void qc.invalidateQueries({ queryKey: ['learn-automations'] })
    },
  })
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Журнал: {rule.title}</DialogTitle>
        </DialogHeader>
        {jobs.isLoading && <SkeletonRows rows={3} />}
        {(jobs.data?.length ?? 0) === 0 && !jobs.isLoading && (
          <p className="py-3 text-center text-sm text-text3">Срабатываний пока нет.</p>
        )}
        <div className="space-y-1">
          {jobs.data?.map((job) => (
            <div
              key={job.id}
              className="flex items-center gap-2 rounded-lg border border-glass-border bg-surface px-3 py-2 text-sm"
            >
              <span className="min-w-0 flex-1 truncate text-text">
                {job.employee_name ?? job.profile_id}
              </span>
              <Badge
                variant={
                  job.status === 'done'
                    ? 'default'
                    : job.status === 'pending'
                      ? 'secondary'
                      : 'outline'
                }
              >
                {JOB_STATUS_LABEL[job.status] ?? job.status}
              </Badge>
              {job.status === 'pending' && (
                <button
                  type="button"
                  title="Отменить"
                  onClick={() => void cancel.mutateAsync(job.id)}
                  className="rounded p-1 text-text3 hover:text-red"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
