import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { AudiencePicker } from '@/components/learn/AudiencePicker'
import { EmployeeListNote } from '@/components/learn/EmployeeListNote'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { FilterChip } from '@/components/ui/FilterChip'
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
import { SearchableSelect } from '@/components/ui/SearchableSelect'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useEmployees, useOrgMutation, useOrgSnapshot, useSites, useSitesPending } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { optionMatches, queryTokens } from '@/lib/selectOptions'
import { AUTH_STATE_LABEL, showAuthStateBadge } from '@/lib/authState'
import type { PointAccount } from '@/lib/learn'
import { shortDate } from '@/lib/taskDates'
import { learnApi, type GroupKind, type MergePreview, type OrgDepartment, type OrgGroup, type OrgRef, type OrgSnapshot, type OrgStore, type SiteMirror, type SitePending } from '@/lib/learn'
import { duplicateGroups, mergeSummary, pendingHint, siteDisplay, sitePickerOptions, type SiteLinkState } from '@/lib/siteLink'

import { useAdminEmbedded } from './adminEmbed'

type TabKey = 'positions' | 'stores' | 'franchisees' | 'departments' | 'groups' | 'access'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'positions', label: 'Должности' },
  { key: 'stores', label: 'Точки' },
  { key: 'franchisees', label: 'Франчайзи' },
  { key: 'departments', label: 'Отделы' },
  { key: 'groups', label: 'Группы' },
  { key: 'access', label: 'Доступы' },
]

export function LearnOrgPage() {
  const isDesktop = useIsDesktop()
  const embedded = useAdminEmbedded()
  const [tab, setTab] = useState<TabKey>('positions')
  const org = useOrgSnapshot()

  return (
    <div className={embedded ? undefined : "mx-auto max-w-5xl"}>
      {!isDesktop && !embedded && <MobilePageHeader eyebrow="Управление" title="Оргструктура" />}
      <div className={embedded ? "space-y-4" : "space-y-4 p-4 lg:p-8"}>
        {isDesktop && !embedded && (
          <h1 className="font-display text-2xl font-bold text-text">Оргструктура</h1>
        )}
        {/* Внутренние разделы — второй ряд ЧИПОВ, не сегментов: вложенные
            сегмент-контролы под сегментами «Управления» читались бы как один. */}
        <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 [scrollbar-width:none] lg:flex-wrap">
          {TABS.map(({ key, label }) => (
            <FilterChip key={key} size="md" active={tab === key} onClick={() => setTab(key)}>
              {label}
            </FilterChip>
          ))}
        </div>

        {org.isLoading && <SkeletonRows rows={6} />}
        {org.isError && <QueryError onRetry={() => void org.refetch()} />}
        {org.data && (
          <>
            {tab === 'positions' && <RefTab kind="positions" refs={org.data.positions} />}
            {tab === 'stores' && <StoresTab org={org.data} />}
            {tab === 'franchisees' && (
              <RefTab kind="franchisees" refs={org.data.franchisees} />
            )}
            {tab === 'departments' && <DepartmentsTab departments={org.data.departments} />}
            {tab === 'groups' && <GroupsTab org={org.data} />}
            {tab === 'access' && <AccessTab />}
          </>
        )}
      </div>
    </div>
  )
}

// ─── Должности / Франчайзи ───────────────────────────────────────────────────

function RefTab({ kind, refs }: { kind: 'positions' | 'franchisees'; refs: OrgRef[] }) {
  const [name, setName] = useState('')
  const [editing, setEditing] = useState<OrgRef | null>(null)
  const create = useOrgMutation((n: string) => learnApi.createRef(kind, { name: n }))
  const update = useOrgMutation(
    (args: { id: string; body: { name?: string; archived?: boolean } }) =>
      learnApi.updateRef(kind, args.id, args.body),
  )
  const remove = useOrgMutation((id: string) => learnApi.deleteRef(kind, id))

  const add = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    await create.mutateAsync(trimmed)
    setName('')
  }

  return (
    <div className="space-y-3">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          void add()
        }}
      >
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={kind === 'positions' ? 'Новая должность…' : 'Новый франчайзи…'}
        />
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          <Plus className="h-4 w-4" /> Добавить
        </Button>
      </form>
      <ul className="divide-y divide-glass-border rounded-xl border border-glass-border bg-glass">
        {refs.length === 0 && (
          <li className="p-4 text-sm text-text3">Пока пусто — добавьте первую запись.</li>
        )}
        {refs.map((r) => (
          <li key={r.id} className="flex items-center gap-2 px-4 py-2.5">
            <span className={cn('flex-1 text-sm', r.archived_at ? 'text-text3 line-through' : 'text-text')}>
              {r.name}
            </span>
            <IconAction
              title="Переименовать"
              onClick={() => setEditing(r)}
              icon={<Pencil className="h-3.5 w-3.5" />}
            />
            <IconAction
              title={r.archived_at ? 'Вернуть из архива' : 'В архив'}
              onClick={() =>
                void update.mutateAsync({ id: r.id, body: { archived: !r.archived_at } })
              }
              icon={
                r.archived_at ? (
                  <ArchiveRestore className="h-3.5 w-3.5" />
                ) : (
                  <Archive className="h-3.5 w-3.5" />
                )
              }
            />
            <IconAction
              title="Удалить"
              onClick={() => void remove.mutateAsync(r.id)}
              icon={<Trash2 className="h-3.5 w-3.5" />}
            />
          </li>
        ))}
      </ul>
      {editing && (
        <RenameDialog
          key={editing.id}
          initialName={editing.name}
          onClose={() => setEditing(null)}
          onSave={async (newName) => {
            await update.mutateAsync({ id: editing.id, body: { name: newName } })
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}

// ─── Магазины ────────────────────────────────────────────────────────────────

function StoresTab({ org }: { org: OrgSnapshot }) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [franchiseeId, setFranchiseeId] = useState('')
  const [editing, setEditing] = useState<OrgStore | null>(null)
  // Зеркало реестра объектов (0053): адрес у магазинов появляется впервые —
  // stores.address пуст у всех, адрес исторически живёт в name.
  const sites = useSites()
  const siteById = useMemo(
    () => new Map((sites.data?.items ?? []).map((x) => [x.site_id, x])),
    [sites.data],
  )
  const snapshotFresh = sites.data?.snapshot_fresh ?? false
  const dupes = useMemo(() => duplicateGroups(org.stores), [org.stores])
  // Объекты реестра, которые автоматика (19.09) не завела карточкой сама —
  // решает человек: создать или привязать к похожей карточке.
  const qc = useQueryClient()
  const pendingSites = useSitesPending()
  const pendingItems = pendingSites.data?.items ?? []
  const invalidatePending = () => void qc.invalidateQueries({ queryKey: ['learn-sites-pending'] })
  // Учётки касс. С 16.09 карточки касс не показываются в «Сотрудниках», и
  // этот раздел — единственное место, где их видно: и привязанные к точке, и
  // осиротевшие (на проде такая одна — auth про неё не знает).
  const accounts = useQuery({
    queryKey: ['learn-point-accounts'],
    queryFn: learnApi.pointAccounts,
    staleTime: 60_000,
  })
  const accountByStore = useMemo(() => {
    const map = new Map<string, PointAccount>()
    for (const a of accounts.data ?? []) if (a.store_id) map.set(a.store_id, a)
    return map
  }, [accounts.data])
  const homeless = useMemo(
    () => (accounts.data ?? []).filter((a) => !a.store_id),
    [accounts.data],
  )

  const create = useOrgMutation(
    (body: { name: string; code?: string; address?: string; franchisee_id?: string | null; site_id?: string | null }) =>
      learnApi.createStore(body),
  )
  const update = useOrgMutation(
    (args: {
      id: string
      body: Partial<{ name: string; code: string | null; franchisee_id: string | null; archived: boolean; site_id: string | null }>
    }) => learnApi.updateStore(args.id, args.body),
  )
  const remove = useOrgMutation((id: string) => learnApi.deleteStore(id))
  const createFromSite = async (p: SitePending) => {
    await create.mutateAsync({
      name: p.name,
      code: p.code ?? undefined,
      address: p.address ?? undefined,
      site_id: p.site_id,
    })
    invalidatePending()
  }
  const linkPending = async (p: SitePending) => {
    if (!p.candidate_store_id) return
    await update.mutateAsync({ id: p.candidate_store_id, body: { site_id: p.site_id } })
    invalidatePending()
  }
  // Слияние пары дублей (19.09): предпросмотр считает сервер, победителя
  // предлагает по данным, админ может поменять местами.
  const [merging, setMerging] = useState<null | { stores: OrgStore[]; winnerId: string; preview: MergePreview | null; loading: boolean }>(null)
  const openMerge = async (group: OrgStore[]) => {
    const [a, b] = group
    if (!a || !b) return
    setMerging({ stores: group, winnerId: a.id, preview: null, loading: true })
    try {
      const preview = await learnApi.mergeStorePreview(b.id, a.id)
      setMerging({ stores: group, winnerId: preview.recommended_winner_id, preview, loading: false })
    } catch (err) {
      toast.error('Не удалось подготовить слияние', { description: (err as Error).message })
      setMerging(null)
    }
  }
  const pickWinner = async (winnerId: string) => {
    if (!merging) return
    const loser = merging.stores.find((s) => s.id !== winnerId)
    if (!loser) return
    setMerging({ ...merging, winnerId, loading: true })
    const preview = await learnApi.mergeStorePreview(loser.id, winnerId)
    setMerging({ ...merging, winnerId, preview, loading: false })
  }
  const merge = useOrgMutation(async (args: { loserId: string; winnerId: string }) => learnApi.mergeStore(args.loserId, args.winnerId))
  const confirmMerge = async () => {
    if (!merging) return
    const loser = merging.stores.find((s) => s.id !== merging.winnerId)
    const winner = merging.stores.find((s) => s.id === merging.winnerId)
    if (!loser || !winner) return
    const r = await merge.mutateAsync({ loserId: loser.id, winnerId: winner.id })
    invalidatePending()
    setMerging(null)
    toast.success(`«${loser.name}» слита в «${winner.name}»`, { description: mergeSummary(r.counts) })
  }

  const franchiseeName = (id: string | null) =>
    org.franchisees.find((f) => f.id === id)?.name ?? null

  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (!name.trim()) return
          void create
            .mutateAsync({
              name: name.trim(),
              code: code.trim() || undefined,
              franchisee_id: franchiseeId || null,
            })
            .then(() => {
              setName('')
              setCode('')
              setFranchiseeId('')
            })
        }}
      >
        <Input
          className="min-w-[160px] flex-1"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Название точки…"
        />
        <Input
          className="w-24"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Код"
        />
        <SearchableSelect
          className="w-44"
          sheetTitle="Франчайзи"
          placeholder="Собственный"
          clearLabel="Собственный"
          aria-label="Франчайзи"
          value={franchiseeId || null}
          onChange={(v) => setFranchiseeId(v ?? '')}
          options={org.franchisees
            .filter((f) => !f.archived_at)
            .map((f) => ({ value: f.id, label: f.name }))}
        />
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          <Plus className="h-4 w-4" /> Добавить
        </Button>
      </form>
      {pendingItems.length > 0 && (
        <div className="rounded-xl border border-glass-border bg-glass p-3">
          <p className="text-sm font-semibold text-text">
            Объекты реестра без карточки · {pendingItems.length}
          </p>
          <p className="mt-0.5 text-xs text-text3">
            Торгующие точки реестр заводит карточками сам; эти автоматика оставила человеку.
          </p>
          <ul className="mt-2 space-y-2">
            {pendingItems.map((p) => (
              <li key={p.site_id} className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-text">
                    {[p.code, p.name].filter(Boolean).join(' · ')}
                  </span>
                  <span className="block text-xs text-text3">
                    {[p.address, pendingHint(p)].filter(Boolean).join(' — ')}
                  </span>
                </span>
                {p.candidate_store_id && (
                  <Button size="sm" variant="secondary" disabled={update.isPending} onClick={() => void linkPending(p)}>
                    Привязать к «{p.candidate_store_name}»
                  </Button>
                )}
                <Button size="sm" variant="secondary" disabled={create.isPending} onClick={() => void createFromSite(p)}>
                  Создать карточку
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {dupes.length > 0 && (
        <div className="rounded-xl border border-amber/40 bg-amber/5 p-3">
          <p className="text-sm font-semibold text-amber">
            Точки с общим объектом реестра · {dupes.length}
          </p>
          <p className="mt-0.5 text-xs text-text3">
            Каждая пара указывает на одну физическую точку. «Слить» переносит
            сотрудников, группы, закрепления, смены, правила аудиторий и участие в
            гонке на оставшуюся карточку, вторая уходит в архив. Отменить нельзя.
          </p>
          <ul className="mt-2 space-y-1.5">
            {dupes.map((g) => (
              <li key={g.site_id} className="flex flex-wrap items-center gap-2 text-xs text-text2">
                <span className="min-w-0 flex-1">{g.stores.map((x) => x.name).join('  ·  ')}</span>
                {g.stores.length === 2 && (
                  <Button size="sm" variant="secondary" onClick={() => void openMerge(g.stores)}>
                    Слить…
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <Dialog open={merging !== null} onOpenChange={(v) => !v && !merge.isPending && setMerging(null)}>
        <DialogContent>
          {merging && (
            <>
              <DialogHeader>
                <DialogTitle>Слить карточки</DialogTitle>
              </DialogHeader>
              <div className="space-y-3">
                <p className="text-sm text-text2">Какая карточка остаётся? Сервер предлагает по данным — людей больше, участвует в гонке, старше.</p>
                <div className="space-y-1.5">
                  {merging.stores.map((s) => (
                    <label key={s.id} className={cn('flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2', merging.winnerId === s.id ? 'border-amber bg-amber/5' : 'border-glass-border')}>
                      <input type="radio" name="merge-winner" checked={merging.winnerId === s.id} onChange={() => void pickWinner(s.id)} disabled={merging.loading || merge.isPending} />
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm text-text">{s.name}</span>
                        <span className="block text-xs text-text3">{s.code ?? 'без кода'}{merging.preview?.recommended_winner_id === s.id && ' · рекомендуется'}</span>
                      </span>
                    </label>
                  ))}
                </div>
                <p className="text-xs text-text2">
                  {merging.loading ? 'Считаем…' : merging.preview ? `К оставшейся карточке перейдёт: ${mergeSummary(merging.preview.counts)}.` : ''}
                </p>
              </div>
              <DialogFooter>
                <Button type="button" variant="secondary" onClick={() => setMerging(null)} disabled={merge.isPending}>
                  Отмена
                </Button>
                <Button type="button" onClick={() => void confirmMerge()} disabled={merging.loading || merge.isPending || !merging.preview}>
                  {merge.isPending ? 'Сливаем…' : 'Слить'}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
      <ul className="divide-y divide-glass-border rounded-xl border border-glass-border bg-glass">
        {org.stores.length === 0 && (
          <li className="p-4 text-sm text-text3">Пока пусто — добавьте первую точку.</li>
        )}
        {org.stores.map((s) => (
          <li key={s.id} className="flex items-center gap-2 px-4 py-2.5">
            {/* Фикс-ширина: строки с кодом и без выравниваются одинаково. */}
            <span className="inline-flex w-12 shrink-0 justify-center">
              {s.code && (
                <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-semibold text-amber">
                  {s.code}
                </span>
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className={cn('block truncate text-sm', s.archived_at ? 'text-text3 line-through' : 'text-text')}>
                {s.name}
                {franchiseeName(s.franchisee_id) && (
                  <span className="ml-2 text-xs text-text3">
                    · {franchiseeName(s.franchisee_id)}
                  </span>
                )}
              </span>
              <SiteLine state={siteDisplay(s, siteById.get(s.site_id ?? ''), snapshotFresh)} />
              <AccountLine account={accountByStore.get(s.id)} />
            </span>
            <IconAction
              title="Изменить"
              onClick={() => setEditing(s)}
              icon={<Pencil className="h-3.5 w-3.5" />}
            />
            <IconAction
              title={s.archived_at ? 'Вернуть из архива' : 'В архив'}
              onClick={() =>
                void update.mutateAsync({ id: s.id, body: { archived: !s.archived_at } })
              }
              icon={
                s.archived_at ? (
                  <ArchiveRestore className="h-3.5 w-3.5" />
                ) : (
                  <Archive className="h-3.5 w-3.5" />
                )
              }
            />
            <IconAction
              title="Удалить"
              onClick={() => void remove.mutateAsync(s.id)}
              icon={<Trash2 className="h-3.5 w-3.5" />}
            />
          </li>
        ))}
      </ul>
      <HomelessAccounts accounts={homeless} />

      <Dialog open={editing !== null} onOpenChange={(v) => !v && setEditing(null)}>
        <DialogContent>
          {editing && (
            <StoreEditForm
              store={editing}
              siteState={siteDisplay(editing, siteById.get(editing.site_id ?? ''), snapshotFresh)}
              sites={sites.data?.items ?? []}
              stores={org.stores}
              franchisees={org.franchisees}
              pending={update.isPending}
              onSave={async (body) => {
                await update.mutateAsync({ id: editing.id, body })
                invalidatePending()
                setEditing(null)
              }}
              onCancel={() => setEditing(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

/** Строка под именем магазина: адрес из реестра, метки архива и протухания.
 *  Состояний три, не два — «stale» обязан быть виден (lib/siteLink.ts). */
/**
 * Учётка точки под её названием.
 *
 * Показываем ТОЛЬКО почту и последний вход: это доступ к кассе, поэтому вся
 * ручка стоит под hub-admin и в общий `org_snapshot` не входит. Состояние
 * учётки берём тем же словарём, что «Сотрудники» (`AUTH_STATE_LABEL`), —
 * иначе два экрана про одну кассу сказали бы разное.
 */
function AccountLine({ account }: { account: PointAccount | undefined }) {
  if (!account) {
    return <span className="block text-xs text-text3">учётки нет</span>
  }
  return (
    <span className="block truncate text-xs text-text3">
      {account.email}
      {account.last_activity_at
        ? ` · был ${shortDate(account.last_activity_at)}`
        : ' · не заходила'}
      {showAuthStateBadge(account.auth_state) && (
        <span className="text-amber"> · {AUTH_STATE_LABEL[account.auth_state]}</span>
      )}
    </span>
  )
}

/** Кассы, не привязанные ни к одной точке: иначе они стали бы невидимы. */
function HomelessAccounts({ accounts }: { accounts: PointAccount[] }) {
  if (accounts.length === 0) return null
  return (
    <div className="rounded-xl border border-hair bg-tint p-3">
      <p className="text-[12px] font-bold uppercase tracking-[0.09em] text-text2">
        Учётки без точки
      </p>
      <p className="mt-1 text-xs text-text2">
        Карточки касс, не привязанные к точке. В «Сотрудниках» они не
        показываются — разобрать их можно только здесь.
      </p>
      <ul className="mt-2 flex flex-col gap-1">
        {accounts.map((a) => (
          <li key={a.profile_id} className="text-sm text-text">
            {a.full_name}
            <span className="ml-2 text-xs text-text3">{a.email}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function SiteLine({ state }: { state: SiteLinkState }) {
  if (state.kind === 'none') return null
  if (state.kind === 'stale') {
    return <span className="block text-xs text-amber">данные реестра устарели</span>
  }
  return (
    <span className="block truncate text-xs text-text3">
      {state.site.address ?? state.site.name}
      {state.site.archived_at && <span className="text-amber"> · объект в архиве</span>}
    </span>
  )
}

function StoreEditForm({
  store,
  siteState,
  sites,
  stores,
  franchisees,
  pending,
  onSave,
  onCancel,
}: {
  store: OrgStore
  siteState: SiteLinkState
  sites: SiteMirror[]
  stores: OrgStore[]
  franchisees: OrgRef[]
  pending: boolean
  onSave: (body: {
    name: string
    code: string | null
    franchisee_id: string | null
    site_id: string | null
  }) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName] = useState(store.name)
  const [code, setCode] = useState(store.code ?? '')
  const [franchiseeId, setFranchiseeId] = useState(store.franchisee_id ?? '')
  const [siteId, setSiteId] = useState(store.site_id ?? '')
  // Живые объекты, не занятые другой живой карточкой (+ текущий) — сервер
  // повторяет проверку (422/409), здесь только удобный список.
  const siteOptions = useMemo(
    () => sitePickerOptions(sites, stores, { storeId: store.id, siteId: store.site_id }),
    [sites, stores, store.id, store.site_id],
  )
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!name.trim()) return
        void onSave({
          name: name.trim(),
          code: code.trim() || null,
          franchisee_id: franchiseeId || null,
          site_id: siteId || null,
        })
      }}
    >
      <DialogHeader>
        <DialogTitle>Точка</DialogTitle>
      </DialogHeader>
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="store-name">Название</Label>
          <Input id="store-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="store-code">Код (для отчётов, например П14)</Label>
          <Input id="store-code" value={code} onChange={(e) => setCode(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="store-fr">Франчайзи</Label>
          <SearchableSelect
            id="store-fr"
            sheetTitle="Франчайзи"
            placeholder="Собственный"
            clearLabel="Собственный"
            value={franchiseeId || null}
            onChange={(v) => setFranchiseeId(v ?? '')}
            options={franchisees.map((f) => ({ value: f.id, label: f.name }))}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="store-site">Объект реестра</Label>
          <SearchableSelect
            id="store-site"
            sheetTitle="Объект реестра"
            placeholder="Не привязан"
            clearLabel="Не привязан"
            value={siteId || null}
            onChange={(v) => setSiteId(v ?? '')}
            options={siteOptions}
          />
        </div>
        {siteState.kind !== 'none' && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <Label>Реестр объектов</Label>
              {siteState.kind === 'live' && (
                <button
                  type="button"
                  className="text-xs font-semibold text-amber hover:underline"
                  onClick={() => {
                    setName(siteState.site.name)
                    if (siteState.site.code) setCode(siteState.site.code)
                  }}
                >
                  Заполнить из реестра
                </button>
              )}
            </div>
            {siteState.kind === 'live' ? (
              <SiteCard site={siteState.site} />
            ) : (
              <p className="text-xs text-amber">
                Данные реестра устарели — показаны локальные поля. Обновление
                зеркала вернёт адрес и реквизиты.
              </p>
            )}
          </div>
        )}
      </div>
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={pending}>
          Отмена
        </Button>
        <Button type="submit" disabled={pending || !name.trim()}>
          Сохранить
        </Button>
      </DialogFooter>
    </form>
  )
}

/** Read-only карточка объекта: реестр — источник адреса и реквизитов, править
 *  их в Hub нельзя (и незачем — колонка archived_at магазина остаётся нашей). */
function SiteCard({ site }: { site: SiteMirror }) {
  return (
    <div className="space-y-0.5 rounded-lg border border-glass-border bg-surface px-3 py-2 text-xs text-text2">
      {site.archived_at && (
        <p className="font-semibold text-amber">
          Объект в архиве реестра — точка при этом живёт своей жизнью
        </p>
      )}
      <p>{[site.code, site.name].filter(Boolean).join(' · ')}</p>
      {site.address && <p>{site.address}</p>}
      {(site.legal_name ?? site.inn) && (
        <p>{[site.legal_name, site.inn ? `ИНН ${site.inn}` : null].filter(Boolean).join(' · ')}</p>
      )}
      {(site.email ?? site.phone) && (
        <p>{[site.email, site.phone].filter(Boolean).join(' · ')}</p>
      )}
    </div>
  )
}

// ─── Отделы (дерево) ─────────────────────────────────────────────────────────

function DepartmentsTab({ departments }: { departments: OrgDepartment[] }) {
  const [name, setName] = useState('')
  const [parentId, setParentId] = useState('')
  const create = useOrgMutation((body: { name: string; parent_id?: string | null }) =>
    learnApi.createDepartment(body),
  )
  const remove = useOrgMutation((id: string) => learnApi.deleteDepartment(id))

  const children = useMemo(() => {
    const map = new Map<string | null, OrgDepartment[]>()
    for (const d of departments) {
      const key = d.parent_id
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(d)
    }
    return map
  }, [departments])

  const renderTree = (parent: string | null, depth: number): React.ReactNode =>
    (children.get(parent) ?? []).map((d) => (
      <div key={d.id}>
        <div
          className="flex items-center gap-2 border-b border-glass-border px-4 py-2.5"
          style={{ paddingLeft: `${1 + depth * 1.25}rem` }}
        >
          <span className="flex-1 text-sm text-text">{d.name}</span>
          <IconAction
            title="Удалить"
            onClick={() => void remove.mutateAsync(d.id)}
            icon={<Trash2 className="h-3.5 w-3.5" />}
          />
        </div>
        {renderTree(d.id, depth + 1)}
      </div>
    ))

  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (!name.trim()) return
          void create
            .mutateAsync({ name: name.trim(), parent_id: parentId || null })
            .then(() => {
              setName('')
              setParentId('')
            })
        }}
      >
        <Input
          className="min-w-[160px] flex-1"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Новый отдел…"
        />
        <Select className="w-52" value={parentId} onChange={(e) => setParentId(e.target.value)}>
          <option value="">Верхний уровень</option>
          {departments.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </Select>
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          <Plus className="h-4 w-4" /> Добавить
        </Button>
      </form>
      <div className="rounded-xl border border-glass-border bg-glass">
        {departments.length === 0 ? (
          <p className="p-4 text-sm text-text3">
            Дерево отделов пусто. Материал, выданный отделу, автоматически виден
            и его под-отделам.
          </p>
        ) : (
          renderTree(null, 0)
        )}
      </div>
    </div>
  )
}

// ─── Группы ──────────────────────────────────────────────────────────────────

const GROUP_KINDS: { kind: GroupKind; label: string }[] = [
  { kind: 'position-groups', label: 'Группы должностей' },
  { kind: 'store-groups', label: 'Группы точек' },
  { kind: 'franchisee-groups', label: 'Группы франчайзи' },
  { kind: 'user-groups', label: 'Группы сотрудников' },
]

function GroupsTab({ org }: { org: OrgSnapshot }) {
  const [kind, setKind] = useState<GroupKind>('position-groups')
  const [name, setName] = useState('')
  const [editingMembers, setEditingMembers] = useState<OrgGroup | null>(null)

  const groups: OrgGroup[] =
    kind === 'position-groups'
      ? org.position_groups
      : kind === 'store-groups'
        ? org.store_groups
        : kind === 'franchisee-groups'
          ? org.franchisee_groups
          : org.user_groups

  const create = useOrgMutation((n: string) => learnApi.createGroup(kind, { name: n }))
  const remove = useOrgMutation((id: string) => learnApi.deleteGroup(kind, id))

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1">
        {GROUP_KINDS.map((g) => (
          <button
            key={g.kind}
            onClick={() => setKind(g.kind)}
            className={cn(
              'rounded-md px-2.5 py-1 text-xs font-semibold transition-colors',
              kind === g.kind ? 'bg-surface text-amber' : 'text-text3 hover:text-text2',
            )}
          >
            {g.label}
          </button>
        ))}
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (!name.trim()) return
          void create.mutateAsync(name.trim()).then(() => setName(''))
        }}
      >
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Новая группа… (например «Наставники»)"
        />
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          <Plus className="h-4 w-4" /> Добавить
        </Button>
      </form>
      <ul className="divide-y divide-glass-border rounded-xl border border-glass-border bg-glass">
        {groups.length === 0 && (
          <li className="p-4 text-sm text-text3">Групп пока нет.</li>
        )}
        {groups.map((g) => (
          <li key={g.id} className="flex items-center gap-2 px-4 py-2.5">
            <span className="flex-1 text-sm text-text">{g.name}</span>
            <button
              onClick={() => setEditingMembers(g)}
              className="rounded bg-surface px-2 py-0.5 text-xs text-text2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            >
              {g.member_ids.length} участн.
            </button>
            <IconAction
              title="Удалить"
              onClick={() => void remove.mutateAsync(g.id)}
              icon={<Trash2 className="h-3.5 w-3.5" />}
            />
          </li>
        ))}
      </ul>
      {editingMembers && (
        <GroupMembersDialog
          kind={kind}
          group={editingMembers}
          org={org}
          onClose={() => setEditingMembers(null)}
        />
      )}
    </div>
  )
}

function GroupMembersDialog({
  kind,
  group,
  org,
  onClose,
}: {
  kind: GroupKind
  group: OrgGroup
  org: OrgSnapshot
  onClose: () => void
}) {
  const employees = useEmployees({ status: 'active' })
  const [selected, setSelected] = useState<Set<string>>(new Set(group.member_ids))
  const [query, setQuery] = useState('')
  const save = useOrgMutation((ids: string[]) =>
    learnApi.replaceGroupMembers(kind, group.id, ids),
  )

  const options: { id: string; label: string; meta?: string }[] =
    kind === 'position-groups'
      ? org.positions.map((p) => ({ id: p.id, label: p.name }))
      : kind === 'store-groups'
        ? org.stores.map((s) => ({ id: s.id, label: s.name }))
        : kind === 'franchisee-groups'
          ? org.franchisees.map((f) => ({ id: f.id, label: f.name }))
          : (employees.data?.items ?? []).map((e) => ({
              id: e.id,
              label: e.full_name,
              meta: e.email,
            }))

  // Отмеченные показываем ВСЕГДА, даже когда поиск их не вернул: иначе снять
  // галочку можно было бы, только вспомнив фамилию, — та же причина, по которой
  // `mergeSelected` существует у пикера людей.
  const tokens = queryTokens(query)
  const visible = options.filter(
    (o) =>
      selected.has(o.id) ||
      optionMatches({ value: o.id, label: o.label, meta: o.meta }, tokens),
  )

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>«{group.name}» — участники</DialogTitle>
        </DialogHeader>
        {/* Поиск НАД списком, а не выпадашка: выбор множественный. В группу
            пользователей попадают все активные карточки — на проде их 315, и
            отметить троих прокруткой окна в 288px невозможно. Правило поиска
            общее с выпадашками (`filterOptions`): пословно, `ё→е`, по имени и
            по почте — двух полных тёзок различает именно она. */}
        {options.length > 8 && (
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск…"
            aria-label="Поиск участника"
          />
        )}
        <div className="max-h-72 space-y-0.5 overflow-y-auto">
          {kind === 'user-groups' && employees.isLoading && <SkeletonRows rows={4} />}
          {visible.map((o) => (
            <label
              key={o.id}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-text hover:bg-glass"
            >
              <input
                type="checkbox"
                checked={selected.has(o.id)}
                onChange={() => toggle(o.id)}
                className="h-4 w-4 accent-[#FFB200]"
              />
              {o.label}
            </label>
          ))}
          {/* Гейт на !isLoading обязателен: условия «идёт загрузка» и «опций
              ноль» независимы, и во время добора экран показывал скелетон И
              «Нет доступных участников.» одновременно — читалось как «в группу
              некого добавить». */}
          {visible.length === 0 && !(kind === 'user-groups' && employees.isLoading) && (
            <p className="p-2 text-sm text-text3">
              {options.length === 0 ? 'Нет доступных участников.' : 'Ничего не найдено.'}
            </p>
          )}
        </div>
        {kind === 'user-groups' && <EmployeeListNote data={employees.data} />}
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            type="button"
            disabled={save.isPending}
            onClick={() =>
              void save.mutateAsync([...selected]).then(() => {
                toast.success('Состав группы обновлён')
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

// ─── Доступы (проверка аудитории + пересчёт) ─────────────────────────────────

function AccessTab() {
  const [rebuilding, setRebuilding] = useState(false)
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-glass-border bg-glass p-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="text-sm font-semibold text-text">Проверка аудитории</p>
            <p className="mt-0.5 text-xs text-text3">
              Соберите правила и посмотрите, кто увидит материал. Этот же
              конструктор используется при публикации контента.
            </p>
          </div>
        </div>
        <div className="mt-3">
          <AudiencePicker />
        </div>
      </div>
      <div className="flex items-center justify-between rounded-xl border border-glass-border bg-glass p-4">
        <div>
          <p className="text-sm font-semibold text-text">Пересчитать доступы</p>
          <p className="mt-0.5 text-xs text-text3">
            Полный пересчёт членства всех аудиторий — страховка при подозрении
            на рассинхрон.
          </p>
        </div>
        <Button
          variant="secondary"
          disabled={rebuilding}
          onClick={() => {
            setRebuilding(true)
            void learnApi
              .audienceRebuild()
              .then((r) => toast.success(`Пересчитано. Изменено аудиторий: ${r.audiences_changed}`))
              .finally(() => setRebuilding(false))
          }}
        >
          <RefreshCw className={cn('h-4 w-4', rebuilding && 'animate-spin')} />
          Пересчитать
        </Button>
      </div>
    </div>
  )
}

// ─── Мелочи ──────────────────────────────────────────────────────────────────

function IconAction({
  title,
  onClick,
  icon,
}: {
  title: string
  onClick: () => void
  icon: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
    >
      {icon}
    </button>
  )
}

function RenameDialog({
  initialName,
  onClose,
  onSave,
}: {
  initialName: string
  onClose: () => void
  onSave: (name: string) => Promise<void>
}) {
  const [name, setName] = useState(initialName)
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) void onSave(name.trim())
          }}
        >
          <DialogHeader>
            <DialogTitle>Переименовать</DialogTitle>
          </DialogHeader>
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} />
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={!name.trim()}>
              Сохранить
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
