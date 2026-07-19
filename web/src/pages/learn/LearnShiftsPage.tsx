import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CalendarClock,
  Check,
  GraduationCap,
  Handshake,
  MapPin,
  Plus,
  X,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'
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
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import {
  learnApi,
  SHIFT_STATUS_LABEL,
  type ShiftPosting,
  type ShiftPostingCreate,
} from '@/lib/learn'

/**
 * Биржа смен (Ф7, ТЗ §24). Сотрудник видит открытые смены своей должности
 * и откликается (сервер проверяет обучение); руководитель публикует смены
 * своих магазинов и подтверждает отклики (или auto_confirm).
 */

function when(startsAt: string, endsAt: string): string {
  const start = new Date(startsAt)
  const end = new Date(endsAt)
  const day = start.toLocaleDateString('ru-RU', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
  const time = (d: Date) =>
    d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return `${day} · ${time(start)}–${time(end)}`
}

const MY_STATUS_LABEL: Record<string, string> = {
  pending: 'отклик отправлен',
  accepted: 'вы назначены',
  declined: 'выбрали другого',
  withdrawn: 'отклик отозван',
}

function useShiftMutation<TArgs>(fn: (args: TArgs) => Promise<void>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    meta: { suppressGlobalError: true },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['learn-shifts'] }),
    onError: (e) => toast.error('Не получилось', { description: extractErrorDetail(e) }),
  })
}

function ShiftCard({
  shift,
  manage,
}: {
  shift: ShiftPosting
  manage: boolean
}) {
  const applyShift = useShiftMutation((id: string) => learnApi.applyShift(id))
  const withdrawShift = useShiftMutation((id: string) => learnApi.withdrawShift(id))
  const acceptApp = useShiftMutation((id: string) => learnApi.acceptShiftApplication(id))
  const cancelShift = useShiftMutation((id: string) => learnApi.cancelShift(id))
  const completeShift = useShiftMutation((id: string) => learnApi.completeShift(id))

  const statusTone =
    shift.status === 'open'
      ? 'border-amber/40'
      : shift.status === 'assigned'
        ? 'border-green/40'
        : 'border-glass-border opacity-75'

  return (
    <div className={cn('rounded-xl border bg-glass p-4', statusTone)}>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={shift.status === 'open' ? 'default' : 'secondary'}>
          {SHIFT_STATUS_LABEL[shift.status]}
        </Badge>
        <span className="inline-flex items-center gap-1 text-xs text-text3">
          <MapPin className="h-3.5 w-3.5" /> {shift.store_name ?? 'Магазин'}
        </span>
        <span className="inline-flex items-center gap-1 text-xs text-text3">
          <CalendarClock className="h-3.5 w-3.5" /> {when(shift.starts_at, shift.ends_at)}
        </span>
      </div>

      <p className="mt-1.5 text-sm font-medium text-text">
        {shift.position_name ?? 'Сотрудник'}
        {shift.pay_note && <span className="text-amber"> · {shift.pay_note}</span>}
      </p>
      {shift.note && <p className="mt-0.5 text-sm text-text2">{shift.note}</p>}

      {shift.required_course_titles.length > 0 && (
        <p className="mt-1 flex items-center gap-1 text-xs text-text3">
          <GraduationCap className="h-3.5 w-3.5" />
          Требуется: {shift.required_course_titles.join(', ')}
        </p>
      )}

      {shift.assigned_name && (
        <p className="mt-1 inline-flex items-center gap-1 text-xs text-green">
          <Check className="h-3.5 w-3.5" /> Назначен(а): {shift.assigned_name}
        </p>
      )}

      {/* Сотрудник */}
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {shift.my_application_status && (
          <span
            className={cn(
              'rounded px-2 py-0.5 text-xs',
              shift.my_application_status === 'accepted'
                ? 'bg-green/15 text-green'
                : 'bg-surface text-text2',
            )}
          >
            {MY_STATUS_LABEL[shift.my_application_status]}
          </span>
        )}
        {shift.can_apply && (
          <Button
            size="sm"
            disabled={applyShift.isPending}
            onClick={() => void applyShift.mutateAsync(shift.id).then(() => toast.success('Отклик отправлен'))}
          >
            <Handshake className="h-4 w-4" /> Откликнуться
          </Button>
        )}
        {!shift.can_apply &&
          !shift.my_application_status &&
          shift.status === 'open' &&
          shift.missing_courses.length > 0 && (
            <span className="text-xs text-red">
              Сначала пройдите: {shift.missing_courses.join(', ')}
            </span>
          )}
        {(shift.my_application_status === 'pending' ||
          shift.my_application_status === 'accepted') &&
          shift.status !== 'cancelled' &&
          shift.status !== 'done' && (
            <Button
              size="sm"
              variant="ghost"
              disabled={withdrawShift.isPending}
              onClick={() => void withdrawShift.mutateAsync(shift.id)}
            >
              Отозвать отклик
            </Button>
          )}
      </div>

      {/* Менеджер: отклики + действия */}
      {manage && shift.applications && shift.applications.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-glass-border pt-2.5">
          {shift.applications.map((app) => (
            <div
              key={app.id}
              className="flex items-center gap-2 rounded-lg border border-glass-border bg-surface px-3 py-1.5 text-sm"
            >
              <span className="min-w-0 flex-1 truncate text-text">
                {app.employee_name}
                {app.comment && (
                  <span className="text-xs text-text3"> — {app.comment}</span>
                )}
              </span>
              <Badge
                variant={
                  app.status === 'accepted'
                    ? 'default'
                    : app.status === 'pending'
                      ? 'secondary'
                      : 'outline'
                }
              >
                {MY_STATUS_LABEL[app.status] ?? app.status}
              </Badge>
              {app.status === 'pending' && shift.status === 'open' && (
                <Button
                  size="sm"
                  disabled={acceptApp.isPending}
                  onClick={() => void acceptApp.mutateAsync(app.id).then(() => toast.success('Назначено'))}
                >
                  Выбрать
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
      {manage && (shift.status === 'open' || shift.status === 'assigned') && (
        <div className="mt-2 flex flex-wrap gap-2">
          {shift.status === 'assigned' && (
            <Button
              size="sm"
              variant="secondary"
              disabled={completeShift.isPending}
              onClick={() => void completeShift.mutateAsync(shift.id)}
            >
              <Check className="h-4 w-4" /> Смена состоялась
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="text-red"
            disabled={cancelShift.isPending}
            onClick={() => {
              if (!window.confirm('Отменить смену? Откликнувшиеся получат уведомление.')) return
              void cancelShift.mutateAsync(shift.id)
            }}
          >
            <X className="h-4 w-4" /> Отменить
          </Button>
        </div>
      )}
    </div>
  )
}

export function LearnShiftsPage() {
  const isDesktop = useIsDesktop()
  const [tab, setTab] = useState<'feed' | 'manage'>('feed')
  const [createOpen, setCreateOpen] = useState(false)

  const feed = useQuery({
    queryKey: ['learn-shifts', false],
    queryFn: () => learnApi.shifts(false),
    staleTime: 15_000,
  })
  const canManage = feed.data?.can_manage ?? false
  const managed = useQuery({
    queryKey: ['learn-shifts', true],
    queryFn: () => learnApi.shifts(true),
    staleTime: 15_000,
    enabled: canManage && tab === 'manage',
  })

  const data = tab === 'manage' ? managed.data : feed.data
  const items = data?.items ?? []

  return (
    <div className="mx-auto max-w-3xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Биржа смен" />}
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex flex-wrap items-center justify-between gap-2">
          {isDesktop && (
            <h1 className="font-display text-2xl font-bold text-text">Биржа смен</h1>
          )}
          <div className="flex items-center gap-2">
            {canManage && (
              <div className="flex items-center gap-1 rounded-lg border border-glass-border p-0.5">
                {(
                  [
                    ['feed', 'Лента'],
                    ['manage', 'Мои смены'],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setTab(key)}
                    className={cn(
                      'rounded px-2.5 py-1 text-xs font-medium',
                      tab === key ? 'bg-surface text-amber' : 'text-text3 hover:text-text',
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
            {canManage && (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" /> Смена
              </Button>
            )}
          </div>
        </div>

        {feed.isLoading && <SkeletonRows rows={4} />}
        {feed.isError && <QueryError onRetry={() => void feed.refetch()} />}

        {data && items.length === 0 && (
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <Handshake className="mx-auto h-8 w-8 text-text3" />
            <p className="mt-3 text-sm text-text2">
              {tab === 'manage'
                ? 'Вы ещё не публиковали смены.'
                : 'Открытых смен для вашей должности пока нет.'}
            </p>
          </div>
        )}

        <div className="space-y-3">
          {items.map((shift) => (
            <ShiftCard key={shift.id} shift={shift} manage={tab === 'manage'} />
          ))}
        </div>

        {createOpen && <CreateShiftDialog onClose={() => setCreateOpen(false)} />}
      </div>
    </div>
  )
}

function CreateShiftDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const org = useOrgSnapshot()
  const courses = useCourses(true)
  const [storeId, setStoreId] = useState('')
  const [positionId, setPositionId] = useState('')
  const [date, setDate] = useState('')
  const [from, setFrom] = useState('09:00')
  const [to, setTo] = useState('18:00')
  const [payNote, setPayNote] = useState('')
  const [note, setNote] = useState('')
  const [requiredCourses, setRequiredCourses] = useState<string[]>([])
  const [autoConfirm, setAutoConfirm] = useState(false)

  const create = useMutation({
    mutationFn: () => {
      const body: ShiftPostingCreate = {
        store_id: storeId,
        position_id: positionId,
        starts_at: new Date(`${date}T${from}`).toISOString(),
        ends_at: new Date(`${date}T${to}`).toISOString(),
        pay_note: payNote.trim() || null,
        note: note.trim() || null,
        required_course_ids: requiredCourses,
        auto_confirm: autoConfirm,
      }
      return learnApi.createShift(body)
    },
    meta: { suppressGlobalError: true },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-shifts'] })
      toast.success('Смена опубликована — подходящие сотрудники получили уведомление')
      onClose()
    },
    onError: (e) =>
      toast.error('Не удалось опубликовать', { description: extractErrorDetail(e) }),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!storeId || !positionId || !date) return
    create.mutate()
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[88vh] overflow-y-auto">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Новая смена</DialogTitle>
          </DialogHeader>
          <div className="space-y-2.5 py-3">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <div>
                <Label htmlFor="sh-store">Магазин</Label>
                <Select
                  id="sh-store"
                  value={storeId}
                  onChange={(e) => setStoreId(e.target.value)}
                >
                  <option value="">— выберите —</option>
                  {(org.data?.stores ?? [])
                    .filter((s) => !s.archived_at)
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="sh-pos">Должность</Label>
                <Select
                  id="sh-pos"
                  value={positionId}
                  onChange={(e) => setPositionId(e.target.value)}
                >
                  <option value="">— выберите —</option>
                  {(org.data?.positions ?? [])
                    .filter((p) => !p.archived_at)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <Label htmlFor="sh-date">Дата</Label>
                <Input
                  id="sh-date"
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="sh-from">С</Label>
                <Input
                  id="sh-from"
                  type="time"
                  value={from}
                  onChange={(e) => setFrom(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="sh-to">До</Label>
                <Input
                  id="sh-to"
                  type="time"
                  value={to}
                  onChange={(e) => setTo(e.target.value)}
                />
              </div>
            </div>
            <div>
              <Label htmlFor="sh-pay">Оплата (текстом, необязательно)</Label>
              <Input
                id="sh-pay"
                value={payNote}
                onChange={(e) => setPayNote(e.target.value)}
                placeholder="например: 350 ₽/час + такси"
                maxLength={255}
              />
            </div>
            <div>
              <Label htmlFor="sh-note">Комментарий</Label>
              <textarea
                id="sh-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                className="flex w-full rounded-lg border border-glass-border bg-glass px-3 py-2 text-sm text-text focus-visible:border-amber focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber"
              />
            </div>
            <div>
              <Label>Обязательное обучение (кандидат должен завершить)</Label>
              <div className="flex flex-wrap gap-1.5">
                {(courses.data?.items ?? [])
                  .filter((c) => c.status === 'published')
                  .map((c) => {
                    const active = requiredCourses.includes(c.id)
                    return (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() =>
                          setRequiredCourses((prev) =>
                            active ? prev.filter((id) => id !== c.id) : [...prev, c.id],
                          )
                        }
                        className={cn(
                          'rounded-full border px-3 py-1 text-xs',
                          active
                            ? 'border-amber/60 bg-amber/10 text-amber'
                            : 'border-glass-border text-text2 hover:text-text',
                        )}
                      >
                        {c.title}
                      </button>
                    )
                  })}
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm text-text2">
              <Switch checked={autoConfirm} onCheckedChange={setAutoConfirm} />
              назначать первого подходящего автоматически
            </label>
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button
              type="submit"
              disabled={!storeId || !positionId || !date || create.isPending}
            >
              Опубликовать
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
