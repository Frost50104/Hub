import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, GraduationCap, Handshake, MapPin, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { QueryError } from '@/components/QueryError'
import { ActionRow } from '@/components/ui/ActionRow'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SegmentGroup, type SegmentOption } from '@/components/ui/SegmentGroup'
import { SearchableSelect } from '@/components/ui/SearchableSelect'
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
  type ShiftPostingUpdate,
} from '@/lib/learn'
import { nbsp, plural } from '@/lib/typography'

/**
 * Биржа смен (Ф7, ТЗ §24) по макету «Урок — редизайн» (route shifts).
 * Сотрудник видит открытые смены своей должности и откликается — сервер
 * проверяет обучение, и без нужного курса вместо кнопки стоит плашка
 * «Сначала пройдите курс …» со ссылкой «К курсу». Руководитель публикует
 * смены своих магазинов («Лента / Мои смены»), правит открытые, подтверждает
 * или отклоняет отклики. Статус смены читается РАМКОЙ карточки (открытая —
 * амбер, назначенная — зелёная, остальные — `--hair`), заливки нет: карточек
 * в списке много.
 */

function when(startsAt: string, endsAt: string): string {
  const start = new Date(startsAt)
  const end = new Date(endsAt)
  const day = start.toLocaleDateString('ru-RU', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
  const time = (d: Date) => d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return nbsp(`${day} · ${time(start)}–${time(end)}`)
}

const MY_STATUS_LABEL: Record<string, string> = {
  pending: 'отклик отправлен',
  accepted: 'вы назначены',
  declined: 'выбрали другого',
  withdrawn: 'отклик отозван',
}

const APP_STATUS_LABEL: Record<string, string> = {
  pending: 'ждёт решения',
  accepted: 'назначен(а)',
  declined: 'отклонён',
  withdrawn: 'отозван',
}

/** Ряд действий: 48px на телефоне, 36px в плотной ленте десктопа. */
const ACTION_BTN =
  'h-12 rounded-xl px-5 text-[15px] lg:h-9 lg:rounded-[10px] lg:px-3.5 lg:text-[13px]'
const GHOST_BTN = cn(ACTION_BTN, 'bg-transparent')

function useShiftMutation<TArgs>(fn: (args: TArgs) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    meta: { suppressGlobalError: true },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['learn-shifts'] }),
    onError: (e) => toast.error('Не получилось', { description: extractErrorDetail(e) }),
  })
}

function cardBorder(status: ShiftPosting['status']): string {
  if (status === 'open') return 'border-amber/45'
  if (status === 'assigned') return 'border-green/40'
  return 'border-hair'
}

function StatusBadge({ status }: { status: ShiftPosting['status'] }) {
  return (
    <Badge
      variant={status === 'open' ? 'default' : status === 'assigned' ? 'success' : 'secondary'}
      className={status !== 'open' && status !== 'assigned' ? 'text-text' : undefined}
    >
      {SHIFT_STATUS_LABEL[status]}
    </Badge>
  )
}

// ─── Карточка в ленте ────────────────────────────────────────────────────────

function FeedCard({
  shift,
  canManage,
  onEdit,
  onCancel,
}: {
  shift: ShiftPosting
  canManage: boolean
  onEdit: () => void
  onCancel: () => void
}) {
  const applyShift = useShiftMutation((id: string) => learnApi.applyShift(id))
  const withdrawShift = useShiftMutation((id: string) => learnApi.withdrawShift(id))
  const completeShift = useShiftMutation((id: string) => learnApi.completeShift(id))

  const mine = shift.my_application_status
  const blocked = shift.status === 'open' && !mine && !shift.can_apply && shift.missing.length > 0
  const canWithdraw =
    (mine === 'pending' || mine === 'accepted') &&
    shift.status !== 'cancelled' &&
    shift.status !== 'done'

  return (
    <article
      className={cn('flex flex-col gap-[9px] rounded-[14px] border bg-tint p-3.5 lg:p-4', cardBorder(shift.status))}
    >
      <div className="flex flex-wrap items-center gap-2 lg:gap-2.5">
        <StatusBadge status={shift.status} />
        <span className="inline-flex items-center gap-[5px] text-[13px] text-text2 lg:text-[14px]">
          <MapPin className="h-3.5 w-3.5" /> {shift.store_name ?? 'Магазин'}
        </span>
        <span className="hidden text-[14px] text-text2 lg:inline">{shift.position_name ?? 'Сотрудник'}</span>
      </div>

      <div className="lg:flex lg:flex-wrap lg:items-baseline lg:gap-3">
        <p className="text-[17px] font-semibold leading-[1.3] text-text lg:text-[20px]">
          {when(shift.starts_at, shift.ends_at)}
        </p>
        <p className="mt-1 text-[15px] leading-[1.45] text-text2 lg:hidden">
          {shift.position_name ?? 'Сотрудник'}
          {shift.pay_note && (
            <>
              {' · '}
              <span className="font-semibold text-text">{shift.pay_note}</span>
            </>
          )}
        </p>
        {shift.pay_note && (
          <span className="hidden text-[15px] font-semibold text-text lg:inline">{shift.pay_note}</span>
        )}
      </div>

      {shift.note && (
        <p className="text-[15px] leading-[1.5] text-text2 [text-wrap:pretty] lg:max-w-[560px] lg:text-[16px] lg:leading-[1.55]">
          {shift.note}
        </p>
      )}

      {shift.required_course_titles.length > 0 && (
        <p className="flex items-center gap-1.5 text-[14px] text-text2">
          <GraduationCap className="h-[15px] w-[15px] shrink-0" />
          Требуется: {shift.required_course_titles.join(', ')}
        </p>
      )}

      {shift.assigned_name && (
        <p className="flex items-center gap-1.5 text-[14px] text-green-deep">
          <Check className="h-[15px] w-[15px] shrink-0" /> Назначена: {shift.assigned_name}
        </p>
      )}

      {shift.can_apply && (
        <div className="flex flex-col gap-[7px] lg:flex-row lg:flex-wrap lg:items-center lg:gap-3">
          <Button
            className="h-12 rounded-xl text-[15px] lg:h-10 lg:rounded-[10px] lg:px-[18px]"
            disabled={applyShift.isPending}
            onClick={() =>
              void applyShift.mutateAsync(shift.id).then(() => toast.success('Отклик отправлен'))
            }
          >
            <Handshake className="h-[17px] w-[17px]" /> Откликнуться
          </Button>
          {/* auto_confirm меняет обещание кнопки: отклик сразу назначает смену. */}
          <p className="text-[13px] text-text2 lg:text-[14px]">
            {shift.auto_confirm ? 'Отклик подтверждается автоматически' : 'Отклик подтвердит руководитель'}
          </p>
        </div>
      )}

      {mine && (
        <div className="flex flex-wrap items-center gap-2.5 lg:gap-3">
          <span
            className={cn(
              'inline-flex h-7 items-center rounded-lg px-2.5 text-[14px] font-semibold',
              mine === 'accepted' ? 'bg-green-deep/15 text-green-deep' : 'bg-surface text-text',
            )}
          >
            {MY_STATUS_LABEL[mine] ?? mine}
          </span>
          {canWithdraw && (
            <button
              type="button"
              disabled={withdrawShift.isPending}
              onClick={() => void withdrawShift.mutateAsync(shift.id)}
              className="-my-2 inline-flex min-h-11 items-center px-2.5 text-[15px] font-semibold text-text hover:text-amber focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 rounded-md disabled:opacity-50 lg:min-h-10 lg:-ml-2.5"
            >
              Отозвать отклик
            </button>
          )}
        </div>
      )}

      {blocked && (
        <div className="flex flex-col gap-[9px] rounded-xl border border-hair bg-surface p-3 lg:flex-row lg:flex-wrap lg:items-center lg:justify-between lg:gap-3 lg:px-3.5">
          <p className="min-w-0 flex-1 text-[15px] leading-[1.45] text-text">
            Сначала пройдите {shift.missing.length > 1 ? 'курсы' : 'курс'}{' '}
            {shift.missing.map((m) => `«${m.title}»`).join(', ')} — отклик проверяет обучение.
          </p>
          <Link
            to={`/learn/courses/${shift.missing[0]!.id}`}
            className="inline-flex min-h-11 shrink-0 items-center justify-center rounded-[11px] border border-hair px-4 text-[15px] font-semibold text-text hover:border-amber/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:min-h-10 lg:rounded-[10px]"
          >
            К курсу
          </Link>
        </div>
      )}

      {canManage && (shift.status === 'open' || shift.status === 'assigned') && (
        <ActionRow className="mt-0">
          {shift.status === 'open' && (
            <Button variant="secondary" className={GHOST_BTN} onClick={onEdit}>
              Изменить
            </Button>
          )}
          {shift.status === 'assigned' && (
            <Button
              variant="secondary"
              className={GHOST_BTN}
              disabled={completeShift.isPending}
              onClick={() => void completeShift.mutateAsync(shift.id)}
            >
              <Check className="h-4 w-4" /> Смена состоялась
            </Button>
          )}
          <Button variant="secondary" className={cn(GHOST_BTN, 'text-red')} onClick={onCancel}>
            Снять смену
          </Button>
        </ActionRow>
      )}
    </article>
  )
}

// ─── Карточка «Мои смены» (менеджер) ─────────────────────────────────────────

function ManageCard({
  shift,
  onEdit,
  onCancel,
}: {
  shift: ShiftPosting
  onEdit: () => void
  onCancel: () => void
}) {
  const acceptApp = useShiftMutation((id: string) => learnApi.acceptShiftApplication(id))
  const declineApp = useShiftMutation((id: string) => learnApi.declineShiftApplication(id))
  const completeShift = useShiftMutation((id: string) => learnApi.completeShift(id))
  const apps = shift.applications ?? []
  const live = apps.filter((a) => a.status !== 'withdrawn')
  const pending = live.filter((a) => a.status === 'pending').length
  const responses =
    live.length === 0
      ? 'Откликов пока нет'
      : nbsp(
          plural(live.length, 'отклик', 'отклика', 'откликов') +
            (shift.assigned_name ? ` · назначена: ${shift.assigned_name}` : pending > 0 ? ` · ${pending} ждут решения` : ''),
        )

  return (
    <article className="flex flex-col gap-2.5 rounded-2xl border border-hair p-4 lg:px-5 lg:py-[18px]">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={shift.status} />
        <span className="text-[14px] text-text2">
          {[shift.store_name ?? 'Магазин', shift.position_name ?? 'Сотрудник'].join(' · ')}
        </span>
      </div>
      <div className="lg:flex lg:flex-wrap lg:items-baseline lg:gap-3">
        <p className="text-[17px] font-semibold leading-[1.3] text-text lg:text-[20px]">
          {when(shift.starts_at, shift.ends_at)}
        </p>
        {shift.pay_note && <span className="text-[14px] text-text2">{shift.pay_note}</span>}
      </div>
      <p className="text-[14px] text-text2">{responses}</p>

      {live.length > 0 && (
        <div className="flex flex-col rounded-xl border border-hair bg-tint px-3 py-3 lg:px-3.5">
          {live.map((app, i) => (
            <div
              key={app.id}
              className={cn(
                'flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center lg:gap-2.5',
                i > 0 && 'mt-3 border-t border-hair pt-3 lg:mt-2 lg:pt-2',
              )}
            >
              <span className="min-w-0 flex-1 text-[14px] font-semibold text-text">
                {app.employee_name ?? '—'}
                <span className="font-normal text-text2">
                  {app.position_name && ` · ${app.position_name.toLocaleLowerCase('ru-RU')}`}
                  {shift.required_course_titles.length > 0 &&
                    (app.passed_required
                      ? ` · ${shift.required_course_titles.map((t) => `«${t}»`).join(', ')} ${
                          shift.required_course_titles.length > 1 ? 'пройдены' : 'пройдена'
                        }`
                      : ' · обучение не завершено')}
                  {app.comment && ` — ${app.comment}`}
                </span>
              </span>
              {app.status === 'pending' && shift.status === 'open' ? (
                <div className="flex gap-2">
                  <Button
                    className={ACTION_BTN}
                    disabled={acceptApp.isPending}
                    onClick={() =>
                      void acceptApp.mutateAsync(app.id).then(() => toast.success('Назначено'))
                    }
                  >
                    Подтвердить
                  </Button>
                  <Button
                    variant="secondary"
                    className={GHOST_BTN}
                    disabled={declineApp.isPending}
                    onClick={() => void declineApp.mutateAsync(app.id)}
                  >
                    Отклонить
                  </Button>
                </div>
              ) : (
                <Badge variant={app.status === 'accepted' ? 'success' : 'outline'}>
                  {APP_STATUS_LABEL[app.status] ?? app.status}
                </Badge>
              )}
            </div>
          ))}
        </div>
      )}

      {(shift.status === 'open' || shift.status === 'assigned') && (
        <div className="flex flex-wrap gap-2">
          {shift.status === 'open' && (
            <Button variant="secondary" className={GHOST_BTN} onClick={onEdit}>
              Изменить
            </Button>
          )}
          {shift.status === 'assigned' && (
            <Button
              variant="secondary"
              className={GHOST_BTN}
              disabled={completeShift.isPending}
              onClick={() => void completeShift.mutateAsync(shift.id)}
            >
              <Check className="h-4 w-4" /> Смена состоялась
            </Button>
          )}
          <Button variant="secondary" className={cn(GHOST_BTN, 'text-red')} onClick={onCancel}>
            Снять смену
          </Button>
        </div>
      )}
    </article>
  )
}

// ─── Страница ────────────────────────────────────────────────────────────────

const TABS: SegmentOption<'feed' | 'manage'>[] = [
  { value: 'feed', label: 'Лента' },
  { value: 'manage', label: 'Мои смены' },
]

export function LearnShiftsPage() {
  const isDesktop = useIsDesktop()
  const [tab, setTab] = useState<'feed' | 'manage'>('feed')
  const [formShift, setFormShift] = useState<ShiftPosting | 'new' | null>(null)
  const [cancelShift, setCancelShift] = useState<ShiftPosting | null>(null)

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
  const openCount = (feed.data?.items ?? []).filter((s) => s.status === 'open').length
  const position = feed.data?.my_position_name ?? null
  const counter =
    feed.data === undefined
      ? ''
      : nbsp(
          `Открытых смен: ${openCount}` +
            (position ? ` · моя должность — ${position.toLocaleLowerCase('ru-RU')}` : ''),
        )

  return (
    <div className="mx-auto max-w-[800px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
      <header className="flex flex-col gap-3.5 lg:flex-row lg:flex-wrap lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="mb-1 min-h-[1em] text-[12px] leading-[1.35] text-text2 lg:hidden">{counter}</p>
          <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
            Биржа смен
          </h1>
          <p className="mt-2.5 hidden text-[18px] leading-[1.6] text-text2 lg:block">
            {counter && `${counter}. `}
            Отклик проверяет обучение: без нужного курса кнопки не будет.
          </p>
        </div>
        {canManage && (
          <div className="flex flex-wrap items-center gap-2">
            <SegmentGroup
              ariaLabel="Вид"
              options={TABS}
              value={tab}
              onChange={setTab}
              size={isDesktop ? 'md' : 'lg'}
            />
            <span className="flex-1 lg:hidden" />
            <Button
              onClick={() => setFormShift('new')}
              className="h-12 rounded-xl px-5 text-[15px] lg:h-9 lg:rounded-[10px] lg:px-3.5 lg:text-[13px]"
            >
              <Plus className="h-4 w-4" /> Смена
            </Button>
          </div>
        )}
      </header>

      <div className="mt-[18px] flex flex-col gap-3 lg:mt-5 lg:gap-5">
        {(tab === 'feed' ? feed.isLoading : managed.isLoading) && <SkeletonRows rows={4} />}
        {feed.isError && <QueryError onRetry={() => void feed.refetch()} />}
        {tab === 'manage' && managed.isError && (
          <QueryError onRetry={() => void managed.refetch()} />
        )}

        {data && items.length === 0 && (
          <EmptyState
            layout="card"
            icon={<Handshake className="h-7 w-7" />}
            title={tab === 'manage' ? 'Вы ещё не публиковали смены' : 'Открытых смен пока нет'}
            text={
              tab === 'manage'
                ? 'Опубликуйте смену — подходящие по должности сотрудники получат уведомление.'
                : position
                  ? `Смены для должности «${position}» появятся здесь, как только руководитель их опубликует.`
                  : 'Смены показываются по должности — в вашем профиле она пока не указана.'
            }
            cta={tab === 'manage' && canManage ? 'Опубликовать смену' : undefined}
            onCta={tab === 'manage' && canManage ? () => setFormShift('new') : undefined}
          />
        )}

        {items.map((shift) =>
          tab === 'manage' ? (
            <ManageCard
              key={shift.id}
              shift={shift}
              onEdit={() => setFormShift(shift)}
              onCancel={() => setCancelShift(shift)}
            />
          ) : (
            <FeedCard
              key={shift.id}
              shift={shift}
              canManage={canManage}
              onEdit={() => setFormShift(shift)}
              onCancel={() => setCancelShift(shift)}
            />
          ),
        )}
      </div>

      {formShift !== null && (
        <ShiftFormDialog
          key={formShift === 'new' ? 'new' : formShift.id}
          shift={formShift === 'new' ? null : formShift}
          onClose={() => setFormShift(null)}
        />
      )}
      {cancelShift !== null && (
        <CancelShiftDialog shift={cancelShift} onClose={() => setCancelShift(null)} />
      )}
    </div>
  )
}

// ─── Снять смену ─────────────────────────────────────────────────────────────

function CancelShiftDialog({ shift, onClose }: { shift: ShiftPosting; onClose: () => void }) {
  const cancel = useShiftMutation((id: string) => learnApi.cancelShift(id))
  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title="Снять смену?"
      description={`${when(shift.starts_at, shift.ends_at)} · ${shift.store_name ?? 'Магазин'}. Откликнувшиеся получат уведомление об отмене.`}
      desktopWidth={440}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={cancel.isPending}>
            Оставить
          </Button>
          <Button
            variant="destructive"
            disabled={cancel.isPending}
            onClick={() =>
              void cancel.mutateAsync(shift.id).then(() => {
                toast.success('Смена снята')
                onClose()
              })
            }
          >
            Снять смену
          </Button>
        </>
      }
    >
      <span className="sr-only">Подтверждение</span>
    </ResponsiveDialog>
  )
}

// ─── Форма смены (создание и правка открытой) ────────────────────────────────

function toLocalDate(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function toLocalTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function ShiftFormDialog({ shift, onClose }: { shift: ShiftPosting | null; onClose: () => void }) {
  const qc = useQueryClient()
  const isNew = shift === null
  const org = useOrgSnapshot()
  const courses = useCourses(true)
  const [storeId, setStoreId] = useState(shift?.store_id ?? '')
  const [positionId, setPositionId] = useState(shift?.position_id ?? '')
  const [date, setDate] = useState(shift ? toLocalDate(shift.starts_at) : '')
  const [from, setFrom] = useState(shift ? toLocalTime(shift.starts_at) : '09:00')
  const [to, setTo] = useState(shift ? toLocalTime(shift.ends_at) : '18:00')
  const [payNote, setPayNote] = useState(shift?.pay_note ?? '')
  const [note, setNote] = useState(shift?.note ?? '')
  const [requiredCourses, setRequiredCourses] = useState<string[]>(shift?.required_course_ids ?? [])
  const [autoConfirm, setAutoConfirm] = useState(shift?.auto_confirm ?? false)

  const save = useMutation({
    mutationFn: () => {
      const starts_at = new Date(`${date}T${from}`).toISOString()
      const ends_at = new Date(`${date}T${to}`).toISOString()
      if (isNew) {
        const body: ShiftPostingCreate = {
          store_id: storeId,
          position_id: positionId,
          starts_at,
          ends_at,
          pay_note: payNote.trim() || null,
          note: note.trim() || null,
          required_course_ids: requiredCourses,
          auto_confirm: autoConfirm,
        }
        return learnApi.createShift(body)
      }
      const patch: ShiftPostingUpdate = {
        starts_at,
        ends_at,
        pay_note: payNote.trim() || null,
        note: note.trim() || null,
        required_course_ids: requiredCourses,
        auto_confirm: autoConfirm,
      }
      return learnApi.updateShift(shift.id, patch)
    },
    meta: { suppressGlobalError: true },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-shifts'] })
      toast.success(
        isNew ? 'Смена опубликована — подходящие сотрудники получили уведомление' : 'Смена обновлена',
      )
      onClose()
    },
    onError: (e) =>
      toast.error(isNew ? 'Не удалось опубликовать' : 'Не удалось сохранить', {
        description: extractErrorDetail(e),
      }),
  })

  const valid = Boolean(storeId && positionId && date && from && to)
  const submit = () => {
    if (!valid) return
    save.mutate()
  }

  const FIELD = 'h-12 text-[15px] lg:h-11'

  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={isNew ? 'Новая смена' : 'Изменить смену'}
      description={
        isNew
          ? 'Подходящие по должности сотрудники получат уведомление сразу после публикации.'
          : 'Магазин и должность не меняются: по ним уже разосланы уведомления. Создайте новую смену, если нужна другая точка.'
      }
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button type="button" onClick={submit} disabled={!valid || save.isPending}>
            {save.isPending ? 'Сохраняем…' : isNew ? 'Опубликовать' : 'Сохранить'}
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
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="sh-store">Магазин</Label>
            <SearchableSelect
              id="sh-store"
              sheetTitle="Магазин"
              placeholder="— выберите —"
              clearLabel={null}
              value={storeId || null}
              disabled={!isNew}
              onChange={(v) => setStoreId(v ?? '')}
              className={FIELD}
              options={(org.data?.stores ?? [])
                .filter((s) => !s.archived_at || s.id === storeId)
                .map((s) => ({ value: s.id, label: s.name }))}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="sh-pos">Должность</Label>
            <Select
              id="sh-pos"
              value={positionId}
              disabled={!isNew}
              onChange={(e) => setPositionId(e.target.value)}
              className={FIELD}
            >
              <option value="">— выберите —</option>
              {(org.data?.positions ?? [])
                .filter((p) => !p.archived_at || p.id === positionId)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
            </Select>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="sh-date">Дата</Label>
            <Input id="sh-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className={FIELD} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="sh-from">С</Label>
            <Input id="sh-from" type="time" value={from} onChange={(e) => setFrom(e.target.value)} className={FIELD} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="sh-to">До</Label>
            <Input id="sh-to" type="time" value={to} onChange={(e) => setTo(e.target.value)} className={FIELD} />
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sh-pay">Оплата (текстом, необязательно)</Label>
          <Input
            id="sh-pay"
            value={payNote}
            onChange={(e) => setPayNote(e.target.value)}
            placeholder="например: 350 ₽/час + такси"
            maxLength={255}
            className={FIELD}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sh-note">Комментарий</Label>
          <textarea
            id="sh-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            className="flex w-full rounded-[10px] border border-glass-border bg-surface px-3.5 py-2.5 text-[15px] text-text focus-visible:border-amber focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber"
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label>Обязательное обучение — кандидат должен завершить</Label>
          <div className="flex flex-wrap gap-2">
            {(courses.data?.items ?? [])
              .filter((c) => c.status === 'published' || requiredCourses.includes(c.id))
              .map((c) => {
                const active = requiredCourses.includes(c.id)
                return (
                  <button
                    key={c.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() =>
                      setRequiredCourses((prev) =>
                        active ? prev.filter((id) => id !== c.id) : [...prev, c.id],
                      )
                    }
                    className={cn(
                      'inline-flex min-h-9 items-center rounded-full border px-3.5 text-[13px] font-semibold transition-colors',
                      active
                        ? 'border-transparent bg-amber text-on-amber'
                        : 'border-glass-border text-text2 hover:text-text',
                    )}
                  >
                    {c.title}
                  </button>
                )
              })}
            {courses.data && courses.data.items.length === 0 && (
              <span className="text-[13px] text-text2">Опубликованных курсов пока нет.</span>
            )}
          </div>
        </div>
        <label className="flex min-h-11 cursor-pointer items-center gap-3 text-[15px] text-text">
          <Switch checked={autoConfirm} onCheckedChange={setAutoConfirm} />
          Назначать первого подходящего автоматически
        </label>
      </form>
    </ResponsiveDialog>
  )
}
