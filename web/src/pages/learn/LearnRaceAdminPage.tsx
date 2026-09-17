import { Copy, RefreshCw, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { QueryError } from '@/components/QueryError'
import { ContestFormDialog } from '@/components/race/admin/ContestFormDialog'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Chip } from '@/components/ui/Chip'
import { InfoRow, InfoRows } from '@/components/ui/InfoRows'
import { Input } from '@/components/ui/Input'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SegmentGroup } from '@/components/ui/SegmentGroup'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { Switch } from '@/components/ui/Switch'
import { useAdminContest, useAdminContests, useBaselines, useRaceAdminMutation, useRaceSettings } from '@/hooks/useRace'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { copyToClipboard } from '@/lib/clipboard'
import { cn } from '@/lib/cn'
import { raceApi, type AdminParticipant, type BaselineRow, type ContestDraft, type RaceContest, type RaceRef } from '@/lib/race'
import {
  CONTEST_STATUS_LABEL,
  RACE_STATUS_LABEL,
  canCreateContest,
  defaultDraft,
  draftFromContest,
  parseBaselineInput,
  resolveRaceAdminParams,
  setRaceAdminParams,
  type ContestFormDraft,
} from '@/lib/raceAdmin'
import { formatAvg } from '@/lib/raceBoard'
import { humanDate, todayKey } from '@/lib/taskDates'
import { nbsp, plural } from '@/lib/typography'

import { useAdminEmbedded } from './adminEmbed'

const STATUS_VARIANT: Record<RaceContest['status'], 'default' | 'secondary' | 'success' | 'outline' | 'destructive'> = {
  draft: 'secondary',
  scheduled: 'secondary',
  active: 'default',
  finished: 'outline',
  cancelled: 'destructive',
}

function Card({ title, actions, children, className }: { title: string; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn('rounded-xl border border-hair bg-tint p-4', className)}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-[17px] font-bold text-text">{title}</h2>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  )
}

function Confirm({ open, onOpenChange, title, text, confirmLabel, destructive, pending, onConfirm }: { open: boolean; onOpenChange: (v: boolean) => void; title: string; text: string; confirmLabel: string; destructive?: boolean; pending: boolean; onConfirm: () => void }) {
  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button variant={destructive ? 'destructive' : 'default'} disabled={pending} onClick={onConfirm}>
            {pending ? 'Выполняем…' : confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-[14px] text-text2">{text}</p>
    </ResponsiveDialog>
  )
}

/** Тумблер модуля — виден hub-admin всегда (иначе включить неоткуда). */
function ModuleToggle({ enabled, syncEnabled, hasActive, onChange, pending }: { enabled: boolean; syncEnabled: boolean; hasActive: boolean; onChange: (v: boolean) => void; pending: boolean }) {
  const [confirmOff, setConfirmOff] = useState(false)
  return (
    <section className={cn('flex items-start justify-between gap-4 rounded-xl border p-4', enabled ? 'border-hair bg-tint' : 'border-amber/50 bg-amber/[0.06]')}>
      <div className="min-w-0">
        <p className="font-display text-[17px] font-bold text-text">{enabled ? 'Гусиная гонка включена' : 'Гусиная гонка выключена'}</p>
        <p className="mt-1 text-[14px] text-text2">
          {enabled
            ? 'Сотрудники видят пункт «Гонка», трек и таблицу лидеров; ТВ-ссылка работает; заезды идут по расписанию.'
            : 'Для сотрудников модуля нет: ни пункта в меню, ни экрана, ни пушей. Данные конкурсов сохраняются — включение вернёт всё как было.'}
          {!syncEnabled && ' На этом окружении выгрузка iiko и пуши гонки выключены (staging).'}
        </p>
      </div>
      <div className="flex h-11 w-11 shrink-0 items-center justify-center">
        <Switch
          checked={enabled}
          disabled={pending}
          aria-label="Включить гусиную гонку"
          onCheckedChange={(v) => {
            if (!v && hasActive) setConfirmOff(true)
            else onChange(v)
          }}
        />
      </div>
      <Confirm
        open={confirmOff}
        onOpenChange={setConfirmOff}
        title="Выключить гонку?"
        text="Идёт конкурс. После выключения гуси не двигаются, пуши не уходят, экран пропадает у сотрудников; данные сохранятся, а пропущенные дни можно дотянуть после включения кнопкой «Обновить данные»."
        confirmLabel="Выключить"
        destructive
        pending={pending}
        onConfirm={() => {
          setConfirmOff(false)
          onChange(false)
        }}
      />
    </section>
  )
}

/**
 * «Управление → Гонка»: тумблер модуля, конкурс с формой, заезды, участники,
 * база, ТВ-ссылки. Состояние выбора — в URL (`contest`, `brace`): вкладка
 * перемонтируется при смене `tab`, и `setRaceAdminParams` его не трогает.
 */
export function LearnRaceAdminPage() {
  const embedded = useAdminEmbedded()
  const isDesktop = useIsDesktop()
  const [params, setParams] = useSearchParams()
  const settings = useRaceSettings()
  const enabled = settings.data?.enabled === true
  const contests = useAdminContests(enabled)
  const urlParams = resolveRaceAdminParams(params)
  const contestId = useMemo(() => {
    const list = contests.data ?? []
    if (urlParams.contest && list.some((c) => c.id === urlParams.contest)) return urlParams.contest
    return list[0]?.id ?? null
  }, [contests.data, urlParams.contest])
  const detail = useAdminContest(enabled ? contestId : null)

  const [formOpen, setFormOpen] = useState<'create' | 'edit' | null>(null)
  const [confirm, setConfirm] = useState<null | { kind: 'schedule' } | { kind: 'cancel' } | { kind: 'finish'; race: RaceRef } | { kind: 'recompute' } | { kind: 'revoke'; token: string }>(null)

  const toggle = useRaceAdminMutation((v: boolean) => raceApi.setEnabled(v), 'Не удалось переключить модуль', (r) =>
    toast.success(r.enabled ? 'Гонка включена' : 'Гонка выключена'),
  )
  const create = useRaceAdminMutation((d: ContestDraft) => raceApi.createContest(d), 'Не удалось создать соревнование', (r) => {
    setFormOpen(null)
    setParams(setRaceAdminParams(params, { contest: r.contest.id }), { replace: true })
    toast.success('Черновик создан — проверьте участников и запланируйте')
  })
  const update = useRaceAdminMutation(
    (d: ContestDraft) => raceApi.updateContest(contestId!, d),
    'Не удалось сохранить соревнование',
    () => {
      setFormOpen(null)
      toast.success('Сохранено')
    },
  )
  const schedule = useRaceAdminMutation(() => raceApi.schedule(contestId!), 'Не удалось запланировать', (r) => {
    setConfirm(null)
    const missing = r.needs_baseline_store_ids.length
    toast.success(
      missing
        ? `Запланировано: ${plural(r.races, 'заезд', 'заезда', 'заездов')}. Без базы — ${plural(missing, 'точка', 'точки', 'точек')}, задайте вручную.`
        : `Запланировано: ${plural(r.races, 'заезд', 'заезда', 'заездов')}, база посчитана.`,
    )
  })
  const cancel = useRaceAdminMutation(() => raceApi.cancel(contestId!), 'Не удалось отменить конкурс', () => {
    setConfirm(null)
    toast.success('Конкурс отменён')
  })
  const finish = useRaceAdminMutation((raceId: string) => raceApi.finishRace(raceId), 'Не удалось завершить заезд', (r) => {
    setConfirm(null)
    toast.success(r.pull_ok ? 'Заезд завершён, итоги зафиксированы' : 'Заезд завершён по последним данным (iiko не ответил)')
  })
  const toggleParticipant = useRaceAdminMutation(
    (a: { storeId: string; included: boolean }) => raceApi.toggleParticipant(contestId!, a.storeId, a.included),
    'Не удалось изменить участника',
    (r) => {
      if (r.replaced_store_id) toast.success('Точка включена, дубль подразделения исключён')
    },
  )
  const refresh = useRaceAdminMutation(() => raceApi.refreshParticipants(contestId!), 'Не удалось обновить состав', () => toast.success('Состав обновлён'))
  const sync = useRaceAdminMutation(() => raceApi.sync({}, false), 'Не удалось обновить данные', (r) =>
    toast.success(r.skipped_empty ? 'iiko вернул пустое окно — данные не тронуты' : `Обновлено: ${plural(r.rows, 'строка', 'строки', 'строк')} по ${plural(r.departments, 'подразделению', 'подразделениям', 'подразделениям')}`),
  )
  const createTv = useRaceAdminMutation(() => raceApi.createTvLink(), 'Не удалось создать ссылку', async (r) => {
    const ok = await copyToClipboard(r.url)
    toast.success(ok ? 'Ссылка создана и скопирована' : 'Ссылка создана')
  })
  const revokeTv = useRaceAdminMutation((token: string) => raceApi.revokeTvLink(token), 'Не удалось отозвать ссылку', () => {
    setConfirm(null)
    toast.success('Ссылка отозвана')
  })

  const c = detail.data?.contest ?? null
  const hasActive = (contests.data ?? []).some((x) => x.status === 'active')
  const leagueGroupIds: string[] = [] // снимок лиг хранит только id групп на сервере; форма редактирует список заново
  const initialDraft: ContestFormDraft = useMemo(
    () => (formOpen === 'edit' && c ? draftFromContest(c, leagueGroupIds) : defaultDraft(todayKey())),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [formOpen, c],
  )

  if (settings.isLoading) return <SkeletonRows rows={4} />
  if (settings.isError || !settings.data) return <QueryError onRetry={() => void settings.refetch()} />

  return (
    <div className="flex flex-col gap-4">
      {!embedded && <h1 className="font-display text-[28px] font-bold text-text">Гусиная гонка</h1>}
      <ModuleToggle enabled={enabled} syncEnabled={settings.data.sync_enabled} hasActive={hasActive} pending={toggle.isPending} onChange={(v) => toggle.mutate(v)} />

      {enabled && (
        <>
          {contests.isLoading && <SkeletonRows rows={3} />}
          {contests.isError && <QueryError onRetry={() => void contests.refetch()} />}
          {contests.data && (
            <Card
              title="Соревнование"
              actions={
                <>
                  {contests.data.length > 1 && (
                    <Select
                      value={contestId ?? ''}
                      onChange={(e) => setParams(setRaceAdminParams(params, { contest: e.target.value }), { replace: true })}
                      className="max-w-[260px]"
                    >
                      {contests.data.map((x) => (
                        <option key={x.id} value={x.id}>
                          {x.title} · {CONTEST_STATUS_LABEL[x.status]}
                        </option>
                      ))}
                    </Select>
                  )}
                  {canCreateContest(contests.data) && (
                    <Button onClick={() => setFormOpen('create')}>Новое соревнование</Button>
                  )}
                </>
              }
            >
              {contests.data.length === 0 && (
                <p className="text-[14px] text-text2">Соревнований ещё не было. Создайте первое: участники подтянутся из реестра точек, заезды сгенерируются автоматически.</p>
              )}
              {c && (
                <div className="flex flex-col gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-display text-[18px] font-bold text-text">{c.title}</span>
                    <Badge variant={STATUS_VARIANT[c.status]}>{CONTEST_STATUS_LABEL[c.status]}</Badge>
                  </div>
                  <InfoRows>
                    <InfoRow label="Даты">
                      {humanDate(c.starts_on)} — {humanDate(c.ends_on)}
                    </InfoRow>
                    <InfoRow label="Заезды">
                      {nbsp(`${c.race_length_days} дней · ${plural((c.weeks_total * 7) / c.race_length_days, 'заезд', 'заезда', 'заездов')}`)}
                    </InfoRow>
                    <InfoRow label="База">
                      {c.baseline_mode === 'contest' ? 'на всё соревнование' : 'на каждый заезд'} · ретро {plural(c.baseline_days, 'день', 'дня', 'дней')}
                    </InfoRow>
                    <InfoRow label="Лиги">{c.leagues.length ? c.leagues.map((l) => l.name).join(', ') : 'без лиг'}</InfoRow>
                    {detail.data && (
                      <InfoRow label="Выгрузка iiko">
                        {detail.data.sync.last_success_at ? `успешно ${new Date(detail.data.sync.last_success_at).toLocaleString('ru-RU')}` : 'ещё не было'}
                        {detail.data.sync.last_error && <span className="block text-[12px] text-red">Ошибка: {detail.data.sync.last_error}</span>}
                      </InfoRow>
                    )}
                  </InfoRows>
                  <div className="flex flex-wrap gap-2">
                    {c.status !== 'finished' && c.status !== 'cancelled' && (
                      <Button variant="secondary" className="bg-transparent" onClick={() => setFormOpen('edit')}>
                        Изменить
                      </Button>
                    )}
                    {c.status === 'draft' && <Button onClick={() => setConfirm({ kind: 'schedule' })}>Запланировать</Button>}
                    {(c.status === 'scheduled' || c.status === 'active') && detail.data?.sync_enabled && (
                      <Button variant="secondary" className="bg-transparent" disabled={sync.isPending} onClick={() => sync.mutate(undefined)}>
                        <RefreshCw className={cn('h-4 w-4', sync.isPending && 'animate-spin')} /> Обновить данные сейчас
                      </Button>
                    )}
                    {(c.status === 'scheduled' || c.status === 'active') && (
                      <Button variant="ghost" onClick={() => setConfirm({ kind: 'cancel' })}>
                        Отменить конкурс
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </Card>
          )}

          {detail.isLoading && contestId && <SkeletonRows rows={4} />}
          {detail.data && c && (
            <>
              <Card title="Заезды">
                {c.races.length === 0 ? (
                  <p className="text-[14px] text-text2">Заезды появятся после планирования.</p>
                ) : (
                  <div className="overflow-hidden rounded-lg border border-hair">
                    {c.races.map((r) => (
                      <div key={r.id} className="grid grid-cols-[48px_minmax(0,1fr)_auto] items-center gap-2 border-b border-hair px-3 py-2 last:border-b-0">
                        <span className="font-display text-[15px] font-bold text-text">№ {r.seq}</span>
                        <span className="min-w-0">
                          <span className="block text-[14px] text-text">
                            {humanDate(r.starts_on)} — {humanDate(r.ends_on)}
                          </span>
                          <span className="block text-[12px] text-text2">
                            {RACE_STATUS_LABEL[r.status]}
                            {r.finish_reason === 'forced' && ' · досрочно'}
                          </span>
                        </span>
                        {r.status === 'active' ? (
                          <Button size="sm" variant="ghost" onClick={() => setConfirm({ kind: 'finish', race: r })}>
                            Завершить досрочно
                          </Button>
                        ) : (
                          <Badge variant={r.status === 'finished' ? 'outline' : 'secondary'}>{RACE_STATUS_LABEL[r.status]}</Badge>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              <ParticipantsCard
                rows={detail.data.participants}
                unlinked={detail.data.unlinked_stores}
                editable={c.status !== 'finished' && c.status !== 'cancelled'}
                pending={toggleParticipant.isPending || refresh.isPending}
                onToggle={(storeId, included) => toggleParticipant.mutate({ storeId, included })}
                onRefresh={() => refresh.mutate(undefined)}
              />

              <BaselinesCard
                contest={c}
                raceParam={urlParams.brace}
                onRaceParam={(id) => setParams(setRaceAdminParams(params, { brace: id }), { replace: true })}
                syncEnabled={detail.data.sync_enabled}
                onRecompute={() => setConfirm({ kind: 'recompute' })}
                isDesktop={isDesktop}
              />

              <Card
                title="Ссылка для ТВ"
                actions={
                  <Button size="sm" disabled={createTv.isPending} onClick={() => createTv.mutate(undefined)}>
                    Создать ссылку
                  </Button>
                }
              >
                <p className="mb-2 text-[13px] text-text2">Откройте на телевизоре в браузере во весь экран — панель обновляется сама каждые 5 минут. Ссылка без логина: не публикуйте её.</p>
                {detail.data.tv_links.length === 0 ? (
                  <p className="text-[14px] text-text2">Активных ссылок нет.</p>
                ) : (
                  <ul className="flex flex-col gap-1">
                    {detail.data.tv_links.map((l) => (
                      <li key={l.id} className="flex items-center gap-2 rounded-md border border-hair bg-surface px-3 py-2 text-sm">
                        <code className="flex-1 truncate text-xs text-text">{l.url}</code>
                        <button
                          type="button"
                          aria-label="Скопировать"
                          className="inline-flex h-8 w-8 items-center justify-center rounded text-text2 hover:bg-glass hover:text-text"
                          onClick={async () => {
                            const ok = await copyToClipboard(l.url)
                            toast[ok ? 'success' : 'error'](ok ? 'Скопировано' : 'Не удалось скопировать')
                          }}
                        >
                          <Copy className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          aria-label="Отозвать"
                          className="inline-flex h-8 w-8 items-center justify-center rounded text-text2 hover:bg-glass hover:text-red"
                          onClick={() => setConfirm({ kind: 'revoke', token: l.token })}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </>
          )}
        </>
      )}

      <ContestFormDialog
        open={formOpen !== null}
        onOpenChange={(v) => !v && setFormOpen(null)}
        initial={initialDraft}
        shapeEditable={formOpen === 'create' || c?.status === 'draft'}
        leaguesEditable={formOpen === 'create' || c?.status === 'draft' || c?.status === 'scheduled'}
        submitLabel={formOpen === 'create' ? 'Создать' : 'Сохранить'}
        pending={create.isPending || update.isPending}
        onSubmit={(d) => (formOpen === 'create' ? create.mutate(d) : update.mutate(d))}
      />
      <Confirm
        open={confirm?.kind === 'schedule'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title="Запланировать соревнование?"
        text="Заезды сгенерируются по датам, база посчитается из чеков iiko за ретро-период (точки без данных останутся без базы — их можно задать вручную). Если старт сегодня, первый заезд начнётся сразу."
        confirmLabel="Запланировать"
        pending={schedule.isPending}
        onConfirm={() => schedule.mutate(undefined)}
      />
      <Confirm
        open={confirm?.kind === 'cancel'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title="Отменить конкурс?"
        text="Активный заезд завершится по последним данным, дальнейшие заезды не состоятся. Итоги уже завершённых заездов сохранятся."
        confirmLabel="Отменить конкурс"
        destructive
        pending={cancel.isPending}
        onConfirm={() => cancel.mutate(undefined)}
      />
      <Confirm
        open={confirm?.kind === 'finish'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title={confirm?.kind === 'finish' ? `Завершить заезд № ${confirm.race.seq} сейчас?` : ''}
        text="Итоги зафиксируются по последним данным, места раздадутся. Следующий заезд стартует по расписанию — даты не сдвигаются."
        confirmLabel="Завершить"
        pending={finish.isPending}
        onConfirm={() => confirm?.kind === 'finish' && finish.mutate(confirm.race.id)}
      />
      <Confirm
        open={confirm?.kind === 'recompute'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title="Пересчитать базы из iiko?"
        text="Базы пересчитаются по чекам за ретро-период до старта. Значения, заданные вручную, сохранятся."
        confirmLabel="Пересчитать"
        pending={false}
        onConfirm={() => setConfirm(null)}
      />
      <Confirm
        open={confirm?.kind === 'revoke'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title="Отозвать ТВ-ссылку?"
        text="Телевизор, на котором она открыта, покажет «ссылка недействительна». Новую можно создать сразу."
        confirmLabel="Отозвать"
        destructive
        pending={revokeTv.isPending}
        onConfirm={() => confirm?.kind === 'revoke' && revokeTv.mutate(confirm.token)}
      />
    </div>
  )
}

function ParticipantsCard({ rows, unlinked, editable, pending, onToggle, onRefresh }: { rows: AdminParticipant[]; unlinked: { store_id: string; name: string; code: string | null }[]; editable: boolean; pending: boolean; onToggle: (storeId: string, included: boolean) => void; onRefresh: () => void }) {
  const included = rows.filter((r) => r.included).length
  return (
    <Card
      title="Участники"
      actions={
        editable ? (
          <Button size="sm" variant="secondary" className="bg-transparent" disabled={pending} onClick={onRefresh}>
            Обновить из реестра
          </Button>
        ) : undefined
      }
    >
      <p className="mb-2 text-[13px] text-text2">{nbsp(`Участвуют ${included} из ${rows.length}`)}. Один участник на подразделение iiko: дубли исключены автоматически.</p>
      <div className="overflow-hidden rounded-lg border border-hair">
        {rows.map((p) => (
          <div key={p.store_id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-hair px-3 py-2 last:border-b-0">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                {p.code && (
                  <Chip variant="outline" size="sm">
                    {p.code}
                  </Chip>
                )}
                <span className={cn('truncate text-[14px]', p.included ? 'text-text' : 'text-text2')}>{p.name}</span>
                {p.department_shared_with.length > 0 && (
                  <Badge variant="outline" className="border-amber/60 text-amber">
                    дубль подразделения
                  </Badge>
                )}
                {!p.included && p.exclude_reason === 'manual' && <Badge variant="secondary">исключена</Badge>}
              </div>
              <p className="text-[12px] text-text2">
                iiko {p.department_id.slice(0, 8)}…{p.department_shared_with.length > 0 && ' · делит подразделение с другой точкой — чеки считаются одной'}
              </p>
            </div>
            <div className="flex h-11 w-11 items-center justify-center">
              <Switch checked={p.included} disabled={!editable || pending} aria-label={`Участие: ${p.name}`} onCheckedChange={(v) => onToggle(p.store_id, v)} />
            </div>
          </div>
        ))}
      </div>
      {unlinked.length > 0 && (
        <p className="mt-2 text-[13px] text-text2">
          Не привязаны к реестру объектов и не участвуют: {unlinked.map((s) => s.name).join(', ')}.
        </p>
      )}
    </Card>
  )
}

function BaselinesCard({ contest, raceParam, onRaceParam, syncEnabled, onRecompute, isDesktop }: { contest: RaceContest; raceParam: string | null; onRaceParam: (id: string | null) => void; syncEnabled: boolean; onRecompute: () => void; isDesktop: boolean }) {
  const perRace = contest.baseline_mode === 'race'
  const raceId = perRace ? (raceParam && contest.races.some((r) => r.id === raceParam) ? raceParam : contest.races.find((r) => r.status === 'active')?.id ?? contest.races[0]?.id ?? null) : null
  const baselines = useBaselines(contest.id, raceId)
  const [editing, setEditing] = useState<{ storeId: string; raw: string; error?: string } | null>(null)
  const put = useRaceAdminMutation(
    (a: { storeId: string; value: number | null }) => raceApi.putBaseline(contest.id, a.storeId, { value: a.value, race_id: raceId }),
    'Не удалось сохранить базу',
    () => setEditing(null),
  )
  const recompute = useRaceAdminMutation(() => raceApi.recomputeBaselines(contest.id, { race_id: raceId, force: false }), 'Не удалось пересчитать базы', (r) =>
    toast.success(`Пересчитано: ${r.computed}${r.skipped_manual ? `, ручных сохранено ${r.skipped_manual}` : ''}${r.empty ? `, без данных ${r.empty}` : ''}`),
  )
  const missing = (baselines.data ?? []).filter((b) => b.needs_baseline).length

  return (
    <Card
      title="Базовые значения"
      actions={
        <>
          {perRace && contest.races.length > 0 && raceId && (
            <SegmentGroup ariaLabel="Заезд" options={contest.races.map((r) => ({ value: r.id, label: `№ ${r.seq}` }))} value={raceId} onChange={onRaceParam} size="sm" />
          )}
          {syncEnabled && (
            <Button size="sm" variant="secondary" className="bg-transparent" disabled={recompute.isPending} onClick={() => { onRecompute(); recompute.mutate(undefined) }}>
              Пересчитать из iiko
            </Button>
          )}
        </>
      }
    >
      <p className="mb-2 text-[13px] text-text2">
        Средняя наполняемость чека за ретро-период — старт гуся (100 клеток). Кликните по значению, чтобы задать вручную.
        {missing > 0 && ` Без базы: ${missing}.`}
      </p>
      {baselines.isLoading && <SkeletonRows rows={4} />}
      {baselines.data && (
        <div className="overflow-hidden rounded-lg border border-hair">
          {baselines.data.map((b) => (
            <BaselineRowView
              key={b.store_id}
              b={b}
              editing={editing?.storeId === b.store_id ? editing : null}
              onEdit={(raw) => setEditing({ storeId: b.store_id, raw })}
              onCancel={() => setEditing(null)}
              onSave={() => {
                if (!editing) return
                const parsed = parseBaselineInput(editing.raw)
                if ('error' in parsed) setEditing({ ...editing, error: parsed.error })
                else put.mutate({ storeId: b.store_id, value: parsed.value })
              }}
              onClear={() => put.mutate({ storeId: b.store_id, value: null })}
              pending={put.isPending}
              isDesktop={isDesktop}
            />
          ))}
        </div>
      )}
    </Card>
  )
}

function BaselineRowView({ b, editing, onEdit, onCancel, onSave, onClear, pending, isDesktop }: { b: BaselineRow; editing: { raw: string; error?: string } | null; onEdit: (raw: string) => void; onCancel: () => void; onSave: () => void; onClear: () => void; pending: boolean; isDesktop: boolean }) {
  return (
    <div className={cn('grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-hair px-3 py-2 last:border-b-0', b.needs_baseline && 'border-l-[3px] border-l-amber')}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          {b.code && (
            <Chip variant="outline" size="sm">
              {b.code}
            </Chip>
          )}
          <span className="truncate text-[14px] text-text">{b.name}</span>
          {b.source === 'manual' && <Badge>вручную</Badge>}
          {b.source === 'iiko' && <Badge variant="secondary">iiko</Badge>}
        </div>
        <p className="text-[12px] text-text2">
          {b.needs_baseline
            ? 'Задайте вручную — данных iiko за ретро-период нет'
            : `${b.receipts ? nbsp(`${b.receipts} чеков`) : ''}${b.period_from && b.period_to ? ` · ${humanDate(b.period_from)} — ${humanDate(b.period_to)}` : ''}${b.set_by_name ? ` · ${b.set_by_name}` : ''}`}
        </p>
        {editing?.error && <p className="text-[12px] text-red">{editing.error}</p>}
      </div>
      {editing ? (
        <div className="flex items-center gap-1">
          <Input
            autoFocus
            inputMode="decimal"
            value={editing.raw}
            className="w-[92px] text-right"
            onChange={(e) => onEdit(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSave()
              if (e.key === 'Escape') onCancel()
            }}
          />
          <Button size="sm" disabled={pending} onClick={onSave}>
            ✓
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel}>
            ✕
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-1">
          <button
            type="button"
            className={cn('rounded-md px-2 py-1 font-display text-[16px] font-bold tabular-nums text-text hover:bg-glass', isDesktop && 'min-w-[72px] text-right')}
            title="Задать вручную"
            onClick={() => onEdit(b.value === null ? '' : String(b.value).replace('.', ','))}
          >
            {b.value === null ? '—' : formatAvg(b.value)}
          </button>
          {b.source === 'manual' && (
            <Button size="sm" variant="ghost" disabled={pending} onClick={onClear} title="Снять ручную правку">
              сбросить
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
