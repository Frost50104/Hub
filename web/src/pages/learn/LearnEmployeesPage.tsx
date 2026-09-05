import {
  Archive,
  ArchiveRestore,
  ExternalLink,
  Link2,
  Plus,
  RefreshCw,
  Search,
  Upload,
  UserX,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  AUTH_STATE_LABEL,
  authStateTone,
  HUB_ROLE_LABEL,
  showAuthStateBadge,
  staffSyncToast,
  type AuthState,
} from '@/lib/authState'
import { employeeListCaption } from '@/lib/employeeList'

import { EmployeeListNote } from '@/components/learn/EmployeeListNote'
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

export function LearnEmployeesPage() {
  const isDesktop = useIsDesktop()
  const embedded = useAdminEmbedded()
  const [statusFilter, setStatusFilter] = useState<'active' | 'archived'>('active')
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, 300)
  const [cardOpen, setCardOpen] = useState<EmployeeProfile | 'new' | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [unlinkedOpen, setUnlinkedOpen] = useState(false)

  const org = useOrgSnapshot()
  const employees = useEmployees({
    status: statusFilter,
    q: debouncedSearch.trim() || undefined,
  })
  // Фильтр по статусу учётки — клиентский: набор и так добирается целиком.
  const [authFilter, setAuthFilter] = useState<'all' | 'no_account' | 'not_logged_in'>('all')
  const [syncing, setSyncing] = useState(false)
  const runSync = async () => {
    setSyncing(true)
    try {
      const report = await learnApi.syncStaff()
      const t = staffSyncToast(report)
      if (t.kind === 'success') toast.success(t.text)
      else toast.message(t.text)
      await employees.refetch()
    } catch {
      toast.error('Не удалось синхронизировать с auth')
    } finally {
      setSyncing(false)
    }
  }

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
            <Button onClick={() => setCardOpen('new')}>
              <Plus className="h-4 w-4" /> Сотрудник
            </Button>
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
                <button
                  type="button"
                  onClick={() => setAuthFilter('no_account')}
                  className={cn(
                    'rounded-full border px-2.5 py-0.5 text-xs',
                    authFilter === 'no_account' ? 'border-amber text-text' : 'border-glass-border text-text3',
                  )}
                >
                  Без учётки
                </button>
                <button
                  type="button"
                  onClick={() => setAuthFilter('not_logged_in')}
                  className={cn(
                    'rounded-full border px-2.5 py-0.5 text-xs',
                    authFilter === 'not_logged_in' ? 'border-amber text-text' : 'border-glass-border text-text3',
                  )}
                >
                  Не входили
                </button>
              </div>
            ) : (
              <p className="rounded-lg border border-amber/30 bg-amber/5 px-3 py-2 text-xs text-text2">
                Ожидает обновления auth-сервиса: список пока пополняется только по
                входам сотрудников. Кнопка «Обновить из auth» заработает после выката.
              </p>
            )}
            {(employees.data.invitations?.length ?? 0) > 0 && (
              <div className="rounded-xl border border-glass-border bg-glass">
                <p className="border-b border-glass-border px-4 py-2 text-xs font-bold uppercase tracking-wide text-text2">
                  Приглашены в auth, ещё не приняли ({employees.data.invitations!.length})
                </p>
                {employees.data.invitations!.map((inv) => (
                  <div key={inv.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                    <span className="min-w-0 truncate text-text">
                      {inv.full_name || inv.email}
                      <span className="ml-2 text-xs text-text3">{inv.email}</span>
                    </span>
                    <span className="shrink-0 text-xs text-text3">
                      {HUB_ROLE_LABEL[inv.role] ?? inv.role}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {/* Раньше здесь стояло «Всего: N» над обрезанным до сотни списком —
                экран противоречил сам себе. Правило одно на все четыре места,
                где сотрудников выбирают: `lib/employeeList.ts`. */}
            <p className="text-xs text-text3">
              {employeeListCaption(employees.data.items.length, employees.data.total)}
            </p>
            <ul className="divide-y divide-glass-border rounded-xl border border-glass-border bg-glass">
              {employees.data.items.length === 0 && (
                <li className="p-4 text-sm text-text3">
                  Никого не нашли. Добавьте сотрудника или загрузите CSV.
                </li>
              )}
              {employees.data.items
                .filter(
                  (e) =>
                    authFilter === 'all' ||
                    e.auth_state === authFilter ||
                    // До первого синка «без учётки» приходит осторожным not_linked.
                    (authFilter === 'no_account' && e.auth_state === 'not_linked'),
                )
                .map((e) => (
                <li key={e.id}>
                  <button
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-surface/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                    onClick={() => setCardOpen(e)}
                  >
                    <div className="min-w-0 flex-1">
                      <p className={cn('truncate text-sm font-medium', e.status === 'archived' ? 'text-text3' : 'text-text')}>
                        {e.full_name}
                      </p>
                      <p className="truncate text-xs text-text3">
                        {[positionName(e.position_id), storeName(e.store_id), e.email]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                    </div>
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
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {cardOpen !== null && org.data && (
        <EmployeeCardDialog
          key={cardOpen === 'new' ? 'new' : cardOpen.id}
          profile={cardOpen === 'new' ? null : cardOpen}
          org={org.data}
          onClose={() => setCardOpen(null)}
        />
      )}
      {importOpen && <ImportDialog onClose={() => setImportOpen(false)} />}
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
  onClose,
}: {
  profile: EmployeeProfile | null
  org: OrgSnapshot
  onClose: () => void
}) {
  const isNew = profile === null
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
  const [tuStores, setTuStores] = useState<Set<string> | null>(
    profile && profile.org_role === 'tu' ? new Set(profile.tu_store_ids) : null,
  )
  // Имя и email принадлежат auth и приезжают оттуда при каждом входе человека.
  // Признак «уже заходил» — last_activity_at, а не наличие аккаунта: карточку
  // можно привязать вручную (/link, /restore), и до первого входа её ещё
  // осмысленно править (ОС 28.08).
  const authOwnsIdentity = !isNew && profile.last_activity_at !== null

  const managers = useEmployees({ status: 'active' })

  const save = useEmployeeMutation(async () => {
    const { email, full_name, ...rest } = form
    const identity = { email: email.trim(), full_name: full_name.trim() }
    // Поля, которыми владеет auth, из тела ИСКЛЮЧАЮТСЯ, а не шлются как есть:
    // сервер отклоняет отличающееся значение, а форма отправляет объект
    // целиком — иначе сохранение должности или роли ловило бы 422 на ровном
    // месте. При создании карточки владельца ещё нет, там поля обязательны.
    const saved = isNew
      ? await learnApi.createEmployee({ ...rest, ...identity })
      : await learnApi.updateEmployee(
          profile.id,
          authOwnsIdentity ? rest : { ...rest, ...identity },
        )
    if (form.org_role === 'tu' && tuStores !== null) {
      await learnApi.replaceTuStores(saved.id, [...tuStores])
    }
    return saved
  })
  // Списочная ручка `archived_twin` не заполняет — тянем одиночную.
  const full = useEmployee(isNew ? null : profile.id)
  const twin = full.data?.archived_twin ?? null
  const archive = useEmployeeMutation(() => learnApi.archiveEmployee(profile!.id))
  const restore = useEmployeeMutation(() => learnApi.restoreEmployee(profile!.id))

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const submit = async () => {
    // У карточки, которой владеет auth, эти поля недоступны и не отправляются —
    // требовать их заполненности незачем.
    if (!authOwnsIdentity && (!form.email.trim() || !form.full_name.trim())) return
    await save.mutateAsync(undefined as never)
    toast.success(isNew ? 'Карточка создана' : 'Сохранено')
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
            <DialogTitle>{isNew ? 'Новый сотрудник' : profile.full_name}</DialogTitle>
            {isNew && (
              <DialogDescription>
                Карточка создаётся заранее — при первом входе через SSO она
                привяжется по email автоматически.
              </DialogDescription>
            )}
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
                  autoFocus={isNew}
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
              <div className="space-y-1.5">
                <Label htmlFor="emp-hired">Дата найма</Label>
                <Input
                  id="emp-hired"
                  type="date"
                  value={form.hired_at ?? ''}
                  onChange={(e) => set('hired_at', e.target.value || null)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="emp-role">Контур</Label>
                <Select
                  id="emp-role"
                  value={form.org_role}
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
                  onChange={(e) => set('position_id', e.target.value || null)}
                >
                  <option value="">—</option>
                  {org.positions
                    .filter((p) => !p.archived_at)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                </Select>
              </div>
              {form.org_role !== 'office' && (
                <div className="space-y-1.5">
                  <Label htmlFor="emp-store">Магазин</Label>
                  <Select
                    id="emp-store"
                    value={form.store_id ?? ''}
                    onChange={(e) => set('store_id', e.target.value || null)}
                  >
                    <option value="">—</option>
                    {org.stores
                      .filter((s) => !s.archived_at)
                      .map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                  </Select>
                </div>
              )}
              {form.org_role === 'office' && (
                <div className="space-y-1.5">
                  <Label htmlFor="emp-dep">Отдел</Label>
                  <Select
                    id="emp-dep"
                    value={form.department_id ?? ''}
                    onChange={(e) => set('department_id', e.target.value || null)}
                  >
                    <option value="">—</option>
                    {org.departments.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
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
                    onChange={(e) => set('franchisee_id', e.target.value || null)}
                  >
                    <option value="">—</option>
                    {org.franchisees
                      .filter((f) => !f.archived_at)
                      .map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))}
                  </Select>
                </div>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="emp-manager">Руководитель</Label>
                <Select
                  id="emp-manager"
                  value={form.manager_profile_id ?? ''}
                  onChange={(e) => set('manager_profile_id', e.target.value || null)}
                >
                  <option value="">—</option>
                  {(managers.data?.items ?? [])
                    .filter((m) => m.id !== profile?.id)
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.full_name}
                      </option>
                    ))}
                </Select>
                <EmployeeListNote data={managers.data} />
              </div>
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
            </div>

            {form.org_role === 'tu' && (
              <div className="space-y-1.5">
                <Label>Закреплённые магазины ТУ</Label>
                <div className="max-h-40 space-y-0.5 overflow-y-auto rounded-lg border border-glass-border p-2">
                  {org.stores
                    .filter((s) => !s.archived_at)
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
                  магазинов.
                </p>
              </div>
            )}
          </div>

          <DialogFooter className="flex-wrap">
            {!isNew && profile.status === 'active' && (
              <Button
                type="button"
                variant="secondary"
                disabled={archive.isPending}
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
            {!isNew && profile.status === 'archived' && (
              <Button
                type="button"
                variant="secondary"
                disabled={restore.isPending}
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

function ImportDialog({ onClose }: { onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<ImportReport | null>(null)
  const run = useEmployeeMutation(async (dryRun: boolean) => {
    if (!file) return
    const result = await learnApi.importEmployees(file, { dryRun })
    setReport(result)
    if (!result.dry_run) {
      toast.success(`Импорт завершён: создано ${result.created}, пропущено ${result.skipped}`)
    }
  })

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Импорт сотрудников из CSV</DialogTitle>
          <DialogDescription>
            Колонки: email, full_name (обязательные), phone, position, store,
            department, franchisee, org_role, manager_email, hired_at.
            Разделитель — «;» или «,». Недостающие должности/магазины создадутся
            автоматически, существующие email пропускаются.
          </DialogDescription>
        </DialogHeader>
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
              <p className="text-text">
                {report.dry_run ? 'Проверка (без сохранения):' : 'Результат:'} создано{' '}
                <b>{report.created}</b>, пропущено <b>{report.skipped}</b>
              </p>
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
                  <Select
                    className="flex-1"
                    value={targetProfile}
                    onChange={(e) => setTargetProfile(e.target.value)}
                  >
                    <option value="">Выберите карточку…</option>
                    {unboundProfiles.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.full_name} ({p.email})
                      </option>
                    ))}
                  </Select>
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
