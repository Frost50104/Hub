import {
  Archive,
  ArchiveRestore,
  ExternalLink,
  Link2,
  RefreshCw,
  Search,
  Upload,
  UserX,
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import {
  AUTH_STATE_LABEL,
  authStateTone,
  HUB_ROLE_LABEL,
  showAuthStateBadge,
  staffSyncToast,
  type AuthFilter,
  type AuthState,
} from '@/lib/authState'
import { IMPORT_DIALOG_HINT, importReportLine, importToastText } from '@/lib/employeeImport'
import { extractErrorDetail } from '@/lib/errors'
import {
  hrSyncToastLine,
  isHrFrozenError,
  omitHrFields,
  returnsByItself,
  type HrView,
} from '@/lib/hrLock'
import {
  employeeRowsCaption,
  matchesRowFilter,
  mergeEmployeeRows,
  rowFilterCounts,
} from '@/lib/employeeRows'
import { filterOptions } from '@/lib/selectOptions'

import { EmployeeListNote } from '@/components/learn/EmployeeListNote'
import { HrNotice } from '@/components/learn/HrNotice'
import { HrPendingBanner } from '@/components/learn/HrPendingBanner'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { DateField } from '@/components/ui/DateField'
import { SearchableSelect } from '@/components/ui/SearchableSelect'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import {
  useEmployeeMutation,
  useEmployee,
  useEmployees,
  useOrgSnapshot,
  useUnlinkedLogins,
} from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import {
  learnApi,
  ORG_ROLE_LABEL,
  type EmployeeProfile,
  type EmployeeUpsert,
  type ImportReport,
  type OrgRole,
  type OrgSnapshot,
} from '@/lib/learn'

import { useAdminEmbedded } from './adminEmbed'

/** Порядок чипов: сначала «кто-то должен что-то сделать», потом «ждём». */
const CHIPS: ReadonlyArray<[Exclude<AuthFilter, 'all'>, string]> = [
  ['no_account', 'Без учётки'],
  ['not_logged_in', 'Не входили'],
  ['invited', 'Приглашены'],
]

export function LearnEmployeesPage() {
  const isDesktop = useIsDesktop()
  const embedded = useAdminEmbedded()
  const [statusFilter, setStatusFilter] = useState<'active' | 'archived'>('active')
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, 300)
  const [cardOpen, setCardOpen] = useState<EmployeeProfile | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [unlinkedOpen, setUnlinkedOpen] = useState(false)

  const org = useOrgSnapshot()
  const employees = useEmployees({
    status: statusFilter,
    q: debouncedSearch.trim() || undefined,
  })
  // Фильтр по статусу учётки — клиентский: набор и так добирается целиком.
  const [authFilter, setAuthFilter] = useState<AuthFilter>('all')
  // Карточки и приглашения — ОДИН список. Отдельный блок «Приглашены в auth»
  // стоял первым и не слушался ни поиска, ни чипов (ОС 17.09); вдобавок 62 из
  // 69 его строк дублировали список под собой. Правила — `lib/employeeRows.ts`.
  const allRows = useMemo(
    () => mergeEmployeeRows(employees.data?.items ?? [], employees.data?.invitations ?? []),
    [employees.data],
  )
  const visibleRows = useMemo(
    () => allRows.filter((row) => matchesRowFilter(authFilter, row)),
    [allRows, authFilter],
  )
  const chipCounts = useMemo(() => rowFilterCounts(allRows), [allRows])
  const [syncing, setSyncing] = useState(false)
  const qc = useQueryClient()
  const hr = org.data?.hr ?? null
  const runSync = async () => {
    setSyncing(true)
    try {
      const report = await learnApi.syncStaff()
      const t = staffSyncToast(report)
      // Кадровые данные из auth (16d) — вторая строка того же тоста.
      const description = hrSyncToastLine(report.hr) ?? undefined
      if (t.kind === 'success') toast.success(t.text, { description })
      else toast.message(t.text, { description })
      await employees.refetch()
      void qc.invalidateQueries({ queryKey: ['learn-org'] })
      void qc.invalidateQueries({ queryKey: ['learn-hr-pending'] })
    } catch {
      toast.error('Не удалось синхронизировать с auth')
    } finally {
      setSyncing(false)
    }
  }


  /**
   * Строка сотрудника. Вынесена из JSX-перебора, потому что список теперь
   * разнородный: карточки соседствуют с приглашениями, у которых карточки нет.
   */
  const renderProfileRow = (e: EmployeeProfile) => (
    <li key={e.id}>
                <button
                  className="flex w-full flex-wrap items-center gap-3 gap-y-1.5 px-4 py-2.5 text-left hover:bg-surface/50 md:flex-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                  onClick={() => setCardOpen(e)}
                >
                  {/* На телефоне имени гарантированы 160 px, а бейджи одной
                      группой уезжают на вторую строку, если не помещаются
                      рядом (ОС 21.09: у 13 строк — ТУ, приглашённые, офис —
                      ФИО сжималось в 0, а экран ездил вбок до 519 px). У
                      `Badge` базовый `shrink-0`, поэтому сжимать некому, кроме
                      имени. С md — прежняя однострочная раскладка. */}
                  <div className="min-w-0 grow basis-40 md:basis-0">
                    <p className={cn('truncate text-sm font-medium', e.status === 'archived' ? 'text-text3' : 'text-text')}>
                      {e.full_name}
                    </p>
                    <p className="truncate text-xs text-text3">
                      {[
                        e.status === 'archived' && e.archive_reason === 'auth_deactivated'
                          ? 'учётка отключена в auth'
                          : null,
                        positionName(e.position_id),
                        storeName(e.store_id),
                        e.email,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                  </div>
                  <span className="flex flex-wrap items-center gap-1.5 md:shrink-0 md:flex-nowrap md:gap-3">
                    {e.hub_role && (
                      <Badge variant="outline" className="text-text2">
                        {HUB_ROLE_LABEL[e.hub_role] ?? e.hub_role}
                      </Badge>
                    )}
                    {e.org_role !== 'employee' && (
                      <Badge variant="outline">{ORG_ROLE_LABEL[e.org_role]}</Badge>
                    )}
                    {/* Честный статус учётки — одна серверная функция вместо
                        двух рассинхронённых признаков (staff-sync, 0052).
                        Фолбэк для протухшего кэша без auth_state — старое
                        правило по employee_id. */}
                    {e.status === 'active' && showAuthStateBadge(e.auth_state as AuthState | null) && (
                      <Badge
                        variant="outline"
                        className={cn(
                          authStateTone(e.auth_state as AuthState) === 'red' ? 'text-red' : 'text-amber',
                        )}
                      >
                        {AUTH_STATE_LABEL[e.auth_state as AuthState]}
                      </Badge>
                    )}
                    {e.status === 'active' && e.auth_state == null && e.employee_id === null && (
                      <Badge variant="outline" className="text-amber">
                        ещё не входил
                      </Badge>
                    )}
                    {e.status === 'archived' && (
                      <Badge variant="outline" className="text-text3">
                        архив
                      </Badge>
                    )}
                  </span>
                </button>
      </li>
  )

  const positionName = (id: string | null) =>
    org.data?.positions.find((p) => p.id === id)?.name
  const storeName = (id: string | null) => org.data?.stores.find((s) => s.id === id)?.name

  return (
    <div className={embedded ? undefined : "mx-auto max-w-5xl"}>
      {!isDesktop && !embedded && <MobilePageHeader eyebrow="Управление" title="Сотрудники" />}
      <div className={embedded ? "space-y-4" : "space-y-4 p-4 lg:p-8"}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          {isDesktop && !embedded && (
            <h1 className="font-display text-2xl font-bold text-text">Сотрудники</h1>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              disabled={syncing}
              onClick={() => void runSync()}
              title="Подтянуть учётки и hub-роли из auth"
            >
              <RefreshCw className={cn('h-4 w-4', syncing && 'animate-spin')} /> Обновить из auth
            </Button>
            <Button variant="secondary" onClick={() => setUnlinkedOpen(true)}>
              <Link2 className="h-4 w-4" /> Непривязанные входы
            </Button>
            <Button variant="secondary" onClick={() => setImportOpen(true)}>
              <Upload className="h-4 w-4" /> Импорт CSV
            </Button>
            {/* Кнопки «+ Сотрудник» нет с 16.09: карточки заводятся в auth
                (приглашение с ролью Hub) и приезжают синком. */}
            <a
              href="https://auth.signaris.ru/admin/employees"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 self-center text-sm text-amber hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5" /> Учётки в auth
            </a>
          </div>
        </div>

        {/* Предохранитель кадровых данных (16d): изменения из auth ждут hub-admin. */}
        {hr?.state === 'blocked' && <HrPendingBanner />}

        <div className="flex flex-wrap gap-2">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-text3" />
            <Input
              className="pl-8"
              placeholder="Поиск по имени или email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <Select
            className="w-36"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'active' | 'archived')}
          >
            <option value="active">Активные</option>
            <option value="archived">Архив</option>
          </Select>
        </div>

        {employees.isLoading && <SkeletonRows rows={8} />}
        {employees.isError && <QueryError onRetry={() => void employees.refetch()} />}
        {employees.data && (
          <>
            {/* Правда о связке с auth (staff-sync, 0052). */}
            {employees.data.staff_synced_at ? (
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-xs text-text3">
                  Штат из auth: синхронизировано {formatSyncTime(employees.data.staff_synced_at)}
                </p>
                <button
                  type="button"
                  onClick={() => setAuthFilter('all')}
                  className={cn(
                    'rounded-full border px-2.5 py-0.5 text-xs',
                    authFilter === 'all' ? 'border-amber text-text' : 'border-glass-border text-text3',
                  )}
                >
                  Все
                </button>
                {/* Чипы рисуются ТОЛЬКО непустые. Пустой чип выглядит как
                    работающий фильтр, а даёт пустой список — читается как
                    поломка экрана. Наборы непересекающиеся: «Без учётки» —
                    никто не позвал, «Приглашены» — позвали и ждём (ОС 17.09,
                    до правки оба чипа давали одну и ту же выдачу). */}
                {CHIPS.map(([key, label]) =>
                  chipCounts[key] > 0 ? (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setAuthFilter(key)}
                      className={cn(
                        'rounded-full border px-2.5 py-0.5 text-xs',
                        authFilter === key
                          ? 'border-amber text-text'
                          : 'border-glass-border text-text3',
                      )}
                    >
                      {label} ({chipCounts[key]})
                    </button>
                  ) : null,
                )}
              </div>
            ) : (
              <p className="rounded-lg border border-amber/30 bg-amber/5 px-3 py-2 text-xs text-text2">
                Ожидает обновления auth-сервиса: список пока пополняется только по
                входам сотрудников. Кнопка «Обновить из auth» заработает после выката.
              </p>
            )}
            {/* Раньше здесь стояло «Всего: N» над обрезанным до сотни списком —
                экран противоречил сам себе. Правило одно на все четыре места,
                где сотрудников выбирают: `lib/employeeList.ts`. */}
            <p className="text-xs text-text3">
              {employeeRowsCaption(visibleRows.length, allRows.length, {
                filtered: authFilter !== 'all',
              })}
            </p>
            <ul className="divide-y divide-glass-border rounded-xl border border-glass-border bg-glass">
              {visibleRows.length === 0 && (
                <li className="p-4 text-sm text-text3">
                  Никого не нашли. Сотрудники появляются из auth после синхронизации.
                </li>
              )}
              {visibleRows.map((row) =>
                row.kind === 'invitation' ? (
                  /* Приглашение без карточки: строка НЕ кликабельна — открывать
                     нечего, карточки в базе ещё нет. Раньше такие семь строк
                     терялись в блоке из 69 над списком. */
                  <li
                    key={row.id}
                    className="flex flex-wrap items-center gap-3 gap-y-1.5 px-4 py-2.5 md:flex-nowrap"
                  >
                    <div className="min-w-0 grow basis-40 md:basis-0">
                      <p className="truncate text-sm font-medium text-text">{row.name}</p>
                      <p className="truncate text-xs text-text3">{row.invitation.email}</p>
                    </div>
                    <span className="flex flex-wrap items-center gap-1.5 md:shrink-0 md:flex-nowrap md:gap-3">
                      {row.invitation.role && (
                        <Badge variant="outline" className="text-text2">
                          {HUB_ROLE_LABEL[row.invitation.role] ?? row.invitation.role}
                        </Badge>
                      )}
                      <Badge variant="outline" className="text-amber">
                        Приглашён(а), карточки нет
                      </Badge>
                    </span>
                  </li>
                ) : (
                  renderProfileRow(row.profile)
                ),
              )}
            </ul>
          </>
        )}
      </div>

      {cardOpen !== null && org.data && (
        <EmployeeCardDialog
          key={cardOpen.id}
          profile={cardOpen}
          org={org.data}
          hr={hr}
          onClose={() => setCardOpen(null)}
        />
      )}
      {importOpen && <ImportDialog frozen={!!hr?.frozen} onClose={() => setImportOpen(false)} />}
      {unlinkedOpen && <UnlinkedDialog onClose={() => setUnlinkedOpen(false)} />}
    </div>
  )
}

function formatSyncTime(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  if (mins < 1) return 'только что'
  if (mins < 60) return `${mins} мин назад`
  return new Date(iso).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ─── Карточка сотрудника ─────────────────────────────────────────────────────

function EmployeeCardDialog({
  profile,
  org,
  hr,
  onClose,
}: {
  profile: EmployeeProfile
  org: OrgSnapshot
  hr: HrView | null
  onClose: () => void
}) {
  const [form, setForm] = useState<EmployeeUpsert & { email: string; full_name: string }>({
    email: profile?.email ?? '',
    full_name: profile?.full_name ?? '',
    phone: profile?.phone ?? null,
    position_id: profile?.position_id ?? null,
    store_id: profile?.store_id ?? null,
    department_id: profile?.department_id ?? null,
    franchisee_id: profile?.franchisee_id ?? null,
    manager_profile_id: profile?.manager_profile_id ?? null,
    org_role: profile?.org_role ?? 'employee',
    content_role: profile?.content_role ?? 'none',
    hired_at: profile?.hired_at ?? null,
  })
  const [tuQuery, setTuQuery] = useState('')
  const [tuStores, setTuStores] = useState<Set<string> | null>(
    profile && profile.org_role === 'tu' ? new Set(profile.tu_store_ids) : null,
  )
  // Имя и email принадлежат auth и приезжают оттуда при каждом входе человека.
  // Признак «уже заходил» — last_activity_at, а не наличие аккаунта: карточку
  // можно привязать вручную (/link, /restore), и до первого входа её ещё
  // осмысленно править (ОС 28.08).
  const authOwnsIdentity = profile.last_activity_at !== null

  const managers = useEmployees({ status: 'active' })
  const qc = useQueryClient()
  // Списочная ручка `archived_twin` не заполняет — тянем одиночную. Она же —
  // свежий признак заморозки: список мог прийти до каткатa.
  const full = useEmployee(profile.id)
  // Кадровые поля ведёт auth (16d): считает сервер, у касс всегда false.
  const locked = (full.data?.hr_locked ?? profile.hr_locked) === true
  const inWindow = hr?.window === true

  const save = useEmployeeMutation(async () => {
    const { email, full_name, ...rest } = form
    const identity = { email: email.trim(), full_name: full_name.trim() }
    // Поля, которыми владеет auth, из тела ИСКЛЮЧАЮТСЯ, а не шлются как есть:
    // сервер отклоняет отличающееся значение, а форма отправляет объект
    // целиком — иначе сохранение должности или роли ловило бы 422 на ровном
    // месте. У непривязанной legacy-карточки владельца ещё нет — там имя и
    // почту правит HR (почта — ключ будущей привязки).
    const body = authOwnsIdentity ? rest : { ...rest, ...identity }
    // Замороженные кадровые поля не уходят вовсе: сервер отказал бы на
    // изменение, а неизменённые ему не нужны. Точки ТУ — тоже из auth.
    const saved = await learnApi.updateEmployee(profile.id, locked ? omitHrFields(body) : body)
    if (!locked && form.org_role === 'tu' && tuStores !== null) {
      await learnApi.replaceTuStores(saved.id, [...tuStores])
    }
    return saved
  })
  const twin = full.data?.archived_twin ?? null
  const archive = useEmployeeMutation(() => learnApi.archiveEmployee(profile.id))
  const restore = useEmployeeMutation(() => learnApi.restoreEmployee(profile.id))

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const submit = async () => {
    // У карточки, которой владеет auth, эти поля недоступны и не отправляются —
    // требовать их заполненности незачем.
    if (!authOwnsIdentity && (!form.email.trim() || !form.full_name.trim())) return
    try {
      await save.mutateAsync(undefined as never)
    } catch (err) {
      // Отказ заморозки: организацию перевели в auth, пока форма была открыта
      // (или вчерашний список). Тост показал глобальный обработчик; форму
      // перечитываем — кадровые поля с сервера, правки телефона и прав остаются.
      if (isHrFrozenError(extractErrorDetail(err))) {
        void qc.invalidateQueries({ queryKey: ['learn-employees'] })
        void qc.invalidateQueries({ queryKey: ['learn-org'] })
        const fresh = (await full.refetch()).data ?? profile
        setForm((f) => ({
          ...f,
          hired_at: fresh.hired_at,
          org_role: fresh.org_role,
          position_id: fresh.position_id,
          store_id: fresh.store_id,
          department_id: fresh.department_id,
          franchisee_id: fresh.franchisee_id,
          manager_profile_id: fresh.manager_profile_id,
        }))
        setTuStores(fresh.org_role === 'tu' ? new Set(fresh.tu_store_ids) : null)
      }
      return
    }
    toast.success('Сохранено')
    onClose()
  }

  const toggleTuStore = (id: string) => {
    setTuStores((prev) => {
      const base = prev ?? new Set<string>()
      const next = new Set(base)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <DialogHeader>
            <DialogTitle>{profile.full_name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="emp-name">ФИО</Label>
                <Input
                  id="emp-name"
                  value={form.full_name}
                  disabled={authOwnsIdentity}
                  onChange={(e) => set('full_name', e.target.value)}
                />
              </div>
              {twin && (
                // Обычно это новый человек на освободившемся ящике — всё
                // правильно. Но тем же путём проходит ОШИБОЧНАЯ архивация, и
                // без этой строки дубль появлялся бы молча: снятая ветка
                // `needs_restore` была единственным сигналом.
                <p className="text-xs text-text3 sm:col-span-2">
                  В архиве есть карточка с этим адресом: {twin.full_name}
                  {twin.archived_at
                    ? `, ${new Date(twin.archived_at).toLocaleDateString('ru-RU')}`
                    : ''}
                </p>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="emp-email">Email (как в SSO)</Label>
                <Input
                  id="emp-email"
                  type="email"
                  value={form.email}
                  disabled={authOwnsIdentity}
                  onChange={(e) => set('email', e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="emp-phone">Телефон</Label>
                <Input
                  id="emp-phone"
                  value={form.phone ?? ''}
                  onChange={(e) => set('phone', e.target.value || null)}
                />
              </div>
              {/* Права на контент — рядом с телефоном: оба правятся в Hub всегда,
                  а на телефоне идут до кадрового блока, который бывает закрыт. */}
              <div className="space-y-1.5">
                <Label htmlFor="emp-content">Права на контент</Label>
                <Select
                  id="emp-content"
                  value={form.content_role}
                  onChange={(e) =>
                    set('content_role', e.target.value as 'none' | 'author' | 'publisher')
                  }
                >
                  <option value="none">Нет</option>
                  <option value="author">Автор (черновики)</option>
                  <option value="publisher">Публикатор</option>
                </Select>
              </div>
              {locked && hr && <HrNotice view={hr} className="sm:col-span-2" />}
              <div className="space-y-1.5">
                <Label htmlFor="emp-hired">Дата найма</Label>
                <DateField
                  id="emp-hired"
                  value={form.hired_at ?? ''}
                  disabled={locked}
                  onChange={(v) => set('hired_at', v || null)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="emp-role">Контур</Label>
                <Select
                  id="emp-role"
                  value={form.org_role}
                  disabled={locked}
                  onChange={(e) => set('org_role', e.target.value as OrgRole)}
                >
                  {Object.entries(ORG_ROLE_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="emp-position">Должность</Label>
                <Select
                  id="emp-position"
                  value={form.position_id ?? ''}
                  disabled={locked}
                  onChange={(e) => set('position_id', e.target.value || null)}
                >
                  <option value="">—</option>
                  {/* Архивную не предлагаем, но ТЕКУЩЕЕ значение показываем:
                      иначе поле читалось бы «—» (паттерн LearnShiftsPage). */}
                  {org.positions
                    .filter((p) => !p.archived_at || p.id === form.position_id)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.archived_at ? `${p.name} (архив)` : p.name}
                      </option>
                    ))}
                </Select>
              </div>
              {form.org_role !== 'office' && (
                <div className="space-y-1.5">
                  <Label htmlFor="emp-store">Точка</Label>
                  <SearchableSelect
                    id="emp-store"
                    sheetTitle="Точка"
                    value={form.store_id ?? null}
                    disabled={locked}
                    onChange={(v) => set('store_id', v)}
                    options={org.stores
                      .filter((s) => !s.archived_at)
                      .map((s) => ({ value: s.id, label: s.name }))}
                    // Архивный магазин из списка отфильтрован, а в карточке он
                    // мог остаться выбранным — без подписи поле выглядело бы
                    // пустым, и его перезаписали бы, не заметив.
                    currentLabel={org.stores.find((s) => s.id === form.store_id)?.name ?? null}
                  />
                </div>
              )}
              {form.org_role === 'office' && (
                <div className="space-y-1.5">
                  <Label htmlFor="emp-dep">Отдел</Label>
                  <Select
                    id="emp-dep"
                    value={form.department_id ?? ''}
                    disabled={locked}
                    onChange={(e) => set('department_id', e.target.value || null)}
                  >
                    <option value="">—</option>
                    {org.departments
                      .filter((d) => !d.archived_at || d.id === form.department_id)
                      .map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.archived_at ? `${d.name} (архив)` : d.name}
                        </option>
                      ))}
                  </Select>
                </div>
              )}
              {form.org_role === 'franchisee_owner' && (
                <div className="space-y-1.5">
                  <Label htmlFor="emp-fr">Франчайзи</Label>
                  <Select
                    id="emp-fr"
                    value={form.franchisee_id ?? ''}
                    disabled={locked}
                    onChange={(e) => set('franchisee_id', e.target.value || null)}
                  >
                    <option value="">—</option>
                    {org.franchisees
                      .filter((f) => !f.archived_at || f.id === form.franchisee_id)
                      .map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.archived_at ? `${f.name} (архив)` : f.name}
                        </option>
                      ))}
                  </Select>
                </div>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="emp-manager">Руководитель</Label>
                {/* 315 вариантов на проде, а руководителями выбраны 17 — то
                    есть 94% списка прокручивали мимо (ОС 16.09). Источник
                    данных остаётся `useEmployees`, а не `/tenant/members`:
                    там только заходившие в Hub (233 против 315 карточек). */}
                <SearchableSelect
                  id="emp-manager"
                  sheetTitle="Руководитель"
                  value={form.manager_profile_id ?? null}
                  disabled={locked}
                  onChange={(v) => set('manager_profile_id', v)}
                  options={(managers.data?.items ?? [])
                    .filter((m) => m.id !== profile?.id)
                    .map((m) => ({ value: m.id, label: m.full_name, meta: m.email }))}
                  currentLabel={
                    (managers.data?.items ?? []).find((m) => m.id === form.manager_profile_id)
                      ?.full_name ?? null
                  }
                  loading={managers.isFetching}
                />
                <EmployeeListNote data={managers.data} />
              </div>
            </div>

            {form.org_role === 'tu' && locked && (
              <div className="space-y-1.5">
                <p className="text-sm font-medium text-text">Закреплённые точки ТУ</p>
                {/* Набор ведёт auth: вместо 63 неактивных галочек — то, что есть. */}
                {(tuStores?.size ?? 0) === 0 ? (
                  <p className="text-xs text-text3">Точки не закреплены</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {org.stores
                      .filter((s) => tuStores?.has(s.id))
                      .map((s) => (
                        <Badge key={s.id} variant="outline" className="text-text2">
                          {s.archived_at ? `${s.name} (архив)` : s.name}
                        </Badge>
                      ))}
                  </div>
                )}
              </div>
            )}
            {form.org_role === 'tu' && !locked && (
              <div className="space-y-1.5">
                <Label htmlFor="emp-tu-search">Закреплённые точки ТУ</Label>
                {/* Выбор здесь множественный, поэтому не выпадашка, а список с
                    поиском НАД ним: точек 63, и отметить три из них
                    прокруткой в окне высотой 160px неудобно ровно так же, как
                    искать руководителя в списке из 315. Правило фильтрации то
                    же самое — `filterOptions`, пословно и с `ё→е`. */}
                <Input
                  id="emp-tu-search"
                  type="search"
                  value={tuQuery}
                  onChange={(e) => setTuQuery(e.target.value)}
                  placeholder="Поиск точки…"
                />
                <div className="max-h-40 space-y-0.5 overflow-y-auto rounded-lg border border-glass-border p-2">
                  {filterOptions(
                    org.stores
                      .filter((s) => !s.archived_at)
                      .map((s) => ({ value: s.id, label: s.name })),
                    tuQuery,
                  )
                    .map((o) => ({ id: o.value, name: o.label }))
                    .map((s) => {
                      const checked = tuStores?.has(s.id) ?? false
                      return (
                        <label
                          key={s.id}
                          className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm text-text hover:bg-glass"
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleTuStore(s.id)}
                            className="h-4 w-4 accent-[#FFB200]"
                          />
                          {s.name}
                        </label>
                      )
                    })}
                </div>
                <p className="text-[11px] text-text3">
                  ТУ автоматически видит материалы и сотрудников закреплённых
                  точек.
                </p>
              </div>
            )}
          </div>

          {profile.status === 'active' && locked && !inWindow && (
            <p className="mt-3 text-xs text-text3">
              «В архив» освобождает вход. Для отпуска или декрета отключите учётку в auth —
              карточка сохранит историю и вернётся сама.
            </p>
          )}
          {inWindow && (
            <p className="mt-3 text-xs text-text3">
              Идёт перенос кадровых данных в auth — архив и восстановление временно закрыты.
            </p>
          )}
          <DialogFooter className="flex-wrap">
            {profile.status === 'active' && (
              <Button
                type="button"
                variant="secondary"
                disabled={archive.isPending || inWindow}
                onClick={() =>
                  void archive.mutateAsync(undefined as never).then(() => {
                    // Тост называет главное последствие: ящик освободился.
                    // Спрашивать «уволен или временно» мы пробовали и
                    // отказались — выбор можно ответить неверно, а неверный
                    // ответ бесшумно возвращал исходный баг.
                    toast.success(
                      'Карточка в архиве, вход освобождён. История обучения сохранена.',
                    )
                    onClose()
                  })
                }
              >
                <Archive className="h-4 w-4" /> В архив
              </Button>
            )}
            {profile.status === 'archived' && returnsByItself(profile, hr) && (
              // Учётку отключили в auth: карточку вернёт синк, когда её включат.
              // Сервер кнопку отклонил бы (409), пока учётка отключена.
              <p className="self-center text-xs text-text2">
                Вернётся сам, когда учётку включат в auth
              </p>
            )}
            {profile.status === 'archived' && !returnsByItself(profile, hr) && (
              <Button
                type="button"
                variant="secondary"
                disabled={restore.isPending || inWindow}
                onClick={() =>
                  void restore.mutateAsync(undefined as never).then(() => {
                    toast.success('Карточка восстановлена')
                    onClose()
                  })
                }
              >
                <ArchiveRestore className="h-4 w-4" /> Восстановить
              </Button>
            )}
            <div className="flex-1" />
            <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
              Отмена
            </Button>
            <Button
              type="submit"
              disabled={save.isPending || !form.email.trim() || !form.full_name.trim()}
            >
              {save.isPending ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>

    </Dialog>
  )
}

// ─── CSV-импорт ──────────────────────────────────────────────────────────────

function ImportDialog({ frozen, onClose }: { frozen: boolean; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<ImportReport | null>(null)
  const run = useEmployeeMutation(async (dryRun: boolean) => {
    if (!file) return
    const result = await learnApi.importEmployees(file, { dryRun })
    setReport(result)
    if (!result.dry_run) {
      toast.success(importToastText(result))
    }
  })

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Импорт сотрудников из CSV</DialogTitle>
          <DialogDescription>{IMPORT_DIALOG_HINT}</DialogDescription>
        </DialogHeader>
        {frozen && (
          // Кадровые данные ведутся в auth (16d): строка, меняющая кадровое поле
          // сотрудника, — ошибка строки; справочники по имени не создаются.
          <p className="rounded-lg border border-hair bg-tint px-3 py-2 text-xs text-text2">
            Кадровые колонки ведутся в auth — в файле оставьте email и телефон.
          </p>
        )}
        <div className="space-y-3">
          <Input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null)
              setReport(null)
            }}
          />
          {report && (
            <div className="rounded-lg border border-glass-border bg-surface p-3 text-sm">
              <p className="text-text">{importReportLine(report)}</p>
              {report.errors.length > 0 && (
                <ul className="mt-2 max-h-40 space-y-0.5 overflow-y-auto text-xs text-red">
                  {report.errors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose} disabled={run.isPending}>
            Закрыть
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={!file || run.isPending}
            onClick={() => void run.mutateAsync(true as never)}
          >
            Проверить
          </Button>
          <Button
            type="button"
            disabled={!file || run.isPending}
            onClick={() => void run.mutateAsync(false as never)}
          >
            {run.isPending ? 'Импортируем…' : 'Импортировать'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Непривязанные входы ─────────────────────────────────────────────────────

function UnlinkedDialog({ onClose }: { onClose: () => void }) {
  const unlinked = useUnlinkedLogins(true)
  const employees = useEmployees({ status: 'active' })
  const [linking, setLinking] = useState<string | null>(null) // employee_id
  const [targetProfile, setTargetProfile] = useState('')
  const link = useEmployeeMutation((args: { profileId: string; employeeId: string }) =>
    learnApi.linkEmployee(args.profileId, args.employeeId),
  )

  // Цели привязки фильтруются на КЛИЕНТЕ по загруженным профилям: пока хук
  // отдавал первую сотню, карточки из хвоста алфавита выбрать было нельзя
  // вовсе — админ решал, что карточки нет, и заводил дубль (на проде таких
  // непривязанных карточек за границей было 35).
  const unboundProfiles = (employees.data?.items ?? []).filter((p) => p.employee_id === null)

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Непривязанные входы</DialogTitle>
          <DialogDescription>
            Люди, заходившие в Hub, для которых не нашлось HR-карточки (обычно —
            опечатка в email при заведении). Привяжите вход к карточке вручную.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-80 space-y-2 overflow-y-auto">
          {unlinked.isLoading && <SkeletonRows rows={3} />}
          {unlinked.data?.length === 0 && (
            <p className="flex items-center gap-2 p-2 text-sm text-text3">
              <UserX className="h-4 w-4" /> Все входы привязаны — отлично.
            </p>
          )}
          {(unlinked.data ?? []).map((u) => (
            <div key={u.employee_id} className="rounded-lg border border-glass-border p-3">
              <p className="text-sm font-medium text-text">{u.full_name}</p>
              <p className="text-xs text-text3">{u.email}</p>
              {linking === u.employee_id ? (
                <div className="mt-2 flex gap-2">
                  <SearchableSelect
                    className="flex-1"
                    sheetTitle="Карточка сотрудника"
                    placeholder="Выберите карточку…"
                    clearLabel={null}
                    aria-label="Карточка сотрудника"
                    value={targetProfile || null}
                    onChange={(v) => setTargetProfile(v ?? '')}
                    options={unboundProfiles.map((p) => ({
                      value: p.id,
                      label: p.full_name,
                      meta: p.email,
                    }))}
                  />
                  <Button
                    type="button"
                    disabled={!targetProfile || link.isPending}
                    onClick={() =>
                      void link
                        .mutateAsync({ profileId: targetProfile, employeeId: u.employee_id })
                        .then(() => {
                          toast.success('Вход привязан к карточке')
                          setLinking(null)
                          setTargetProfile('')
                        })
                    }
                  >
                    Привязать
                  </Button>
                  <EmployeeListNote data={employees.data} />
                </div>
              ) : (
                <Button
                  type="button"
                  variant="secondary"
                  className="mt-2"
                  onClick={() => {
                    setLinking(u.employee_id)
                    setTargetProfile('')
                  }}
                >
                  <Link2 className="h-3.5 w-3.5" /> Привязать к карточке
                </Button>
              )}
            </div>
          ))}
        </div>
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose}>
            Закрыть
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
