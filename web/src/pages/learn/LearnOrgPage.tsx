import { Archive, ArchiveRestore, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { AudiencePicker } from '@/components/learn/AudiencePicker'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
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
import { useEmployees, useOrgMutation, useOrgSnapshot } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import {
  learnApi,
  type GroupKind,
  type OrgDepartment,
  type OrgGroup,
  type OrgRef,
  type OrgSnapshot,
  type OrgStore,
} from '@/lib/learn'

type TabKey = 'positions' | 'stores' | 'franchisees' | 'departments' | 'groups' | 'access'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'positions', label: 'Должности' },
  { key: 'stores', label: 'Магазины' },
  { key: 'franchisees', label: 'Франчайзи' },
  { key: 'departments', label: 'Отделы' },
  { key: 'groups', label: 'Группы' },
  { key: 'access', label: 'Доступы' },
]

export function LearnOrgPage() {
  const isDesktop = useIsDesktop()
  const [tab, setTab] = useState<TabKey>('positions')
  const org = useOrgSnapshot()

  return (
    <div className="mx-auto max-w-5xl">
      {!isDesktop && <MobilePageHeader eyebrow="Управление" title="Оргструктура" />}
      <div className="space-y-4 p-4 lg:p-8">
        {isDesktop && (
          <h1 className="font-display text-2xl font-bold text-text">Оргструктура</h1>
        )}
        <div className="flex flex-wrap gap-1 rounded-lg border border-glass-border bg-bg-alt/60 p-1">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
                tab === key ? 'bg-surface text-amber' : 'text-text3 hover:text-text2',
              )}
            >
              {label}
            </button>
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

  const create = useOrgMutation(
    (body: { name: string; code?: string; franchisee_id?: string | null }) =>
      learnApi.createStore(body),
  )
  const update = useOrgMutation(
    (args: {
      id: string
      body: Partial<{ name: string; code: string | null; franchisee_id: string | null; archived: boolean }>
    }) => learnApi.updateStore(args.id, args.body),
  )
  const remove = useOrgMutation((id: string) => learnApi.deleteStore(id))

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
          placeholder="Название магазина…"
        />
        <Input
          className="w-24"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Код"
        />
        <Select
          className="w-44"
          value={franchiseeId}
          onChange={(e) => setFranchiseeId(e.target.value)}
        >
          <option value="">Собственный</option>
          {org.franchisees
            .filter((f) => !f.archived_at)
            .map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
        </Select>
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          <Plus className="h-4 w-4" /> Добавить
        </Button>
      </form>
      <ul className="divide-y divide-glass-border rounded-xl border border-glass-border bg-glass">
        {org.stores.length === 0 && (
          <li className="p-4 text-sm text-text3">Пока пусто — добавьте первый магазин.</li>
        )}
        {org.stores.map((s) => (
          <li key={s.id} className="flex items-center gap-2 px-4 py-2.5">
            {s.code && (
              <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-semibold text-amber">
                {s.code}
              </span>
            )}
            <span className={cn('flex-1 text-sm', s.archived_at ? 'text-text3 line-through' : 'text-text')}>
              {s.name}
              {franchiseeName(s.franchisee_id) && (
                <span className="ml-2 text-xs text-text3">
                  · {franchiseeName(s.franchisee_id)}
                </span>
              )}
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

      <Dialog open={editing !== null} onOpenChange={(v) => !v && setEditing(null)}>
        <DialogContent>
          {editing && (
            <StoreEditForm
              store={editing}
              franchisees={org.franchisees}
              pending={update.isPending}
              onSave={async (body) => {
                await update.mutateAsync({ id: editing.id, body })
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

function StoreEditForm({
  store,
  franchisees,
  pending,
  onSave,
  onCancel,
}: {
  store: OrgStore
  franchisees: OrgRef[]
  pending: boolean
  onSave: (body: {
    name: string
    code: string | null
    franchisee_id: string | null
  }) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName] = useState(store.name)
  const [code, setCode] = useState(store.code ?? '')
  const [franchiseeId, setFranchiseeId] = useState(store.franchisee_id ?? '')
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!name.trim()) return
        void onSave({
          name: name.trim(),
          code: code.trim() || null,
          franchisee_id: franchiseeId || null,
        })
      }}
    >
      <DialogHeader>
        <DialogTitle>Магазин</DialogTitle>
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
          <Select
            id="store-fr"
            value={franchiseeId}
            onChange={(e) => setFranchiseeId(e.target.value)}
          >
            <option value="">Собственный</option>
            {franchisees.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </Select>
        </div>
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
  { kind: 'store-groups', label: 'Группы магазинов' },
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
  const save = useOrgMutation((ids: string[]) =>
    learnApi.replaceGroupMembers(kind, group.id, ids),
  )

  const options: { id: string; label: string }[] =
    kind === 'position-groups'
      ? org.positions.map((p) => ({ id: p.id, label: p.name }))
      : kind === 'store-groups'
        ? org.stores.map((s) => ({ id: s.id, label: s.name }))
        : kind === 'franchisee-groups'
          ? org.franchisees.map((f) => ({ id: f.id, label: f.name }))
          : (employees.data?.items ?? []).map((e) => ({ id: e.id, label: e.full_name }))

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
        <div className="max-h-72 space-y-0.5 overflow-y-auto">
          {kind === 'user-groups' && employees.isLoading && <SkeletonRows rows={4} />}
          {options.map((o) => (
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
          {options.length === 0 && (
            <p className="p-2 text-sm text-text3">Нет доступных участников.</p>
          )}
        </div>
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
