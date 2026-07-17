import {
  Archive,
  BookOpen,
  Check,
  CheckCircle2,
  ExternalLink,
  FileText,
  FolderCog,
  Link2,
  Pencil,
  Plus,
  Send,
  Upload,
  Users,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AudiencePicker, type AudienceValue } from '@/components/learn/AudiencePicker'
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
import { Input, Textarea } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useLibrary, useLibraryMutation } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import {
  CONTENT_STATUS_LABEL,
  learnApi,
  type AckReport,
  type ContentStatus,
  type LibraryData,
  type LibraryMaterial,
  type LibrarySection,
  type MaterialUpsert,
} from '@/lib/learn'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

export function LearnLibraryPage() {
  const isDesktop = useIsDesktop()
  const [params, setParams] = useSearchParams()
  const [sectionFilter, setSectionFilter] = useState<string>('')
  const [createOpen, setCreateOpen] = useState(false)
  const [sectionsOpen, setSectionsOpen] = useState(false)

  // Первый запрос без manage; узнав content_role author+, дозапрашиваем
  // manage-представление (черновики и чужие статусы).
  const probe = useLibrary(false)
  const canManage =
    probe.data !== undefined && ['admin', 'publisher', 'author'].includes(probe.data.content_role)
  const managed = useLibrary(true, canManage)
  const data: LibraryData | undefined = canManage ? (managed.data ?? probe.data) : probe.data

  const openedId = params.get('m')
  const openedMaterial = useMemo(
    () => data?.materials.find((m) => m.id === openedId) ?? null,
    [data, openedId],
  )

  const setOpened = (id: string | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('m', id)
    else next.delete('m')
    setParams(next, { replace: true })
  }

  const sections = data?.sections ?? []
  const materials = useMemo(() => {
    let list = data?.materials ?? []
    if (sectionFilter) list = list.filter((m) => m.section_id === sectionFilter)
    return list
  }, [data, sectionFilter])

  const pendingCount = (data?.materials ?? []).filter((m) => m.ack_pending).length

  return (
    <div className="mx-auto max-w-5xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Библиотека" />}
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex flex-wrap items-center justify-between gap-2">
          {isDesktop && (
            <h1 className="font-display text-2xl font-bold text-text">Библиотека</h1>
          )}
          {canManage && (
            <div className="flex flex-wrap gap-2">
              {['admin', 'publisher'].includes(data?.content_role ?? '') && (
                <Button variant="secondary" onClick={() => setSectionsOpen(true)}>
                  <FolderCog className="h-4 w-4" /> Разделы
                </Button>
              )}
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" /> Материал
              </Button>
            </div>
          )}
        </div>

        {pendingCount > 0 && (
          <div className="flex items-center gap-2 rounded-xl border border-amber/40 bg-amber/10 px-4 py-2.5 text-sm text-text">
            <CheckCircle2 className="h-4 w-4 shrink-0 text-amber" />
            Требуют ознакомления: <b>{pendingCount}</b>
          </div>
        )}

        {sections.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            <SectionChip
              label="Все"
              active={sectionFilter === ''}
              onClick={() => setSectionFilter('')}
            />
            {sections.map((s) => (
              <SectionChip
                key={s.id}
                label={s.title}
                active={sectionFilter === s.id}
                onClick={() => setSectionFilter(s.id)}
              />
            ))}
          </div>
        )}

        {probe.isLoading && <SkeletonRows rows={6} />}
        {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}
        {data && materials.length === 0 && (
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <BookOpen className="mx-auto h-8 w-8 text-text3" />
            <p className="mt-3 text-sm text-text2">
              {sectionFilter ? 'В этом разделе пока пусто.' : 'В библиотеке пока пусто.'}
            </p>
            {canManage && (
              <p className="mt-1 text-xs text-text3">
                Нажмите «Материал», чтобы загрузить первый документ.
              </p>
            )}
          </div>
        )}

        <ul className="space-y-2">
          {materials.map((m) => (
            <li key={m.id}>
              <button
                onClick={() => setOpened(m.id)}
                className="flex w-full items-center gap-3 rounded-xl border border-glass-border bg-glass px-4 py-3 text-left transition-colors hover:border-amber/40 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              >
                {m.kind === 'link' ? (
                  <Link2 className="h-5 w-5 shrink-0 text-text3" />
                ) : (
                  <FileText className="h-5 w-5 shrink-0 text-text3" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-text">{m.title}</p>
                  <p className="truncate text-xs text-text3">
                    {[
                      m.current_version
                        ? `v${m.current_version.version_no} · ${formatSize(m.current_version.size_bytes)}`
                        : m.kind === 'link'
                          ? 'внешняя ссылка'
                          : 'файл не загружен',
                      m.owner_name && `владелец: ${m.owner_name}`,
                      `обновлён ${formatDate(m.updated_at)}`,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                </div>
                {canManage && m.status !== 'published' && (
                  <Badge variant="outline" className="text-text3">
                    {CONTENT_STATUS_LABEL[m.status]}
                  </Badge>
                )}
                {m.ack_pending && (
                  <Badge variant="outline" className="border-amber/50 text-amber">
                    ознакомиться
                  </Badge>
                )}
                {m.requires_acknowledgement && m.acked_by_me && (
                  <Check className="h-4 w-4 shrink-0 text-green" />
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>

      {openedMaterial && data && (
        <MaterialDialog
          key={openedMaterial.id}
          material={openedMaterial}
          data={data}
          onClose={() => setOpened(null)}
        />
      )}
      {createOpen && data && (
        <MaterialFormDialog
          data={data}
          material={null}
          onClose={() => setCreateOpen(false)}
        />
      )}
      {sectionsOpen && data && (
        <SectionsDialog sections={data.sections} onClose={() => setSectionsOpen(false)} />
      )}
    </div>
  )
}

function SectionChip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'rounded-full px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
        active ? 'bg-amber text-on-amber' : 'bg-glass text-text2 hover:text-text',
      )}
    >
      {label}
    </button>
  )
}

// ─── Карточка материала ──────────────────────────────────────────────────────

function MaterialDialog({
  material,
  data,
  onClose,
}: {
  material: LibraryMaterial
  data: LibraryData
  onClose: () => void
}) {
  const role = data.content_role
  const isPublisher = role === 'admin' || role === 'publisher'
  const canManage = isPublisher || role === 'author'
  const [openedLocally, setOpenedLocally] = useState(material.opened_by_me)
  const [editOpen, setEditOpen] = useState(false)
  const [audienceOpen, setAudienceOpen] = useState(false)
  const [reportOpen, setReportOpen] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const open = useLibraryMutation(async () => {
    if (material.kind === 'link' && material.url) {
      await learnApi.trackOpen(material.id)
      window.open(material.url, '_blank', 'noopener')
    } else {
      await learnApi.openMaterialFile(material)
    }
    setOpenedLocally(true)
  })
  const ack = useLibraryMutation(() =>
    learnApi.acknowledge(material.id, material.current_version_no ?? 0),
  )
  const setStatus = useLibraryMutation((s: ContentStatus) =>
    learnApi.setMaterialStatus(material.id, s),
  )
  const uploadVersion = useLibraryMutation((file: File) =>
    learnApi.uploadVersion(material.id, file),
  )
  const remove = useLibraryMutation(() => learnApi.deleteMaterial(material.id))

  const section = data.sections.find((s) => s.id === material.section_id)

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {material.kind === 'link' ? (
              <Link2 className="h-4 w-4 text-text3" />
            ) : (
              <FileText className="h-4 w-4 text-text3" />
            )}
            {material.title}
          </DialogTitle>
          {material.description && (
            <DialogDescription>{material.description}</DialogDescription>
          )}
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-text3">
            {section && <p>Раздел: {section.title}</p>}
            {material.owner_name && <p>Владелец: {material.owner_name}</p>}
            {material.current_version && (
              <p>
                Версия {material.current_version.version_no} ·{' '}
                {formatSize(material.current_version.size_bytes)}
              </p>
            )}
            <p>Обновлён: {formatDate(material.updated_at)}</p>
            {material.next_review_at && (
              <p>Проверка актуальности: {formatDate(material.next_review_at)}</p>
            )}
            {canManage && (
              <p>
                Статус:{' '}
                <span className={material.status === 'published' ? 'text-green' : 'text-amber'}>
                  {CONTENT_STATUS_LABEL[material.status]}
                </span>
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => void open.mutateAsync(undefined as never)}
              disabled={
                open.isPending || (material.kind === 'file' && !material.current_version_no)
              }
            >
              <ExternalLink className="h-4 w-4" />
              {material.kind === 'link' ? 'Открыть ссылку' : 'Открыть документ'}
            </Button>
            {material.requires_acknowledgement &&
              material.status === 'published' &&
              !material.acked_by_me && (
                <Button
                  variant="secondary"
                  disabled={!openedLocally || ack.isPending}
                  title={openedLocally ? undefined : 'Сначала откройте документ'}
                  onClick={() =>
                    void ack.mutateAsync(undefined as never).then(() => {
                      toast.success('Ознакомление подтверждено')
                    })
                  }
                >
                  <Check className="h-4 w-4" /> Ознакомлен
                </Button>
              )}
            {material.requires_acknowledgement && material.acked_by_me && (
              <span className="flex items-center gap-1.5 text-sm text-green">
                <Check className="h-4 w-4" /> Ознакомление подтверждено
              </span>
            )}
          </div>

          {canManage && (
            <div className="space-y-2 rounded-lg border border-glass-border bg-surface/50 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-text3">
                Управление
              </p>
              <div className="flex flex-wrap gap-2">
                {material.status === 'draft' && (
                  <Button
                    variant="secondary"
                    disabled={setStatus.isPending}
                    onClick={() => void setStatus.mutateAsync('review')}
                  >
                    <Send className="h-3.5 w-3.5" /> На согласование
                  </Button>
                )}
                {isPublisher && material.status !== 'published' && (
                  <Button
                    disabled={setStatus.isPending}
                    onClick={() =>
                      void setStatus.mutateAsync('published').then(() => {
                        toast.success('Материал опубликован')
                      })
                    }
                  >
                    Опубликовать
                  </Button>
                )}
                {isPublisher && material.status === 'published' && (
                  <Button
                    variant="secondary"
                    disabled={setStatus.isPending}
                    onClick={() => void setStatus.mutateAsync('archived')}
                  >
                    <Archive className="h-3.5 w-3.5" /> В архив
                  </Button>
                )}
                {material.kind === 'file' && (
                  <>
                    <input
                      ref={fileInput}
                      type="file"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0]
                        if (f)
                          void uploadVersion.mutateAsync(f).then(() => {
                            toast.success('Новая версия загружена')
                          })
                        e.target.value = ''
                      }}
                    />
                    <Button
                      variant="secondary"
                      disabled={uploadVersion.isPending}
                      onClick={() => fileInput.current?.click()}
                    >
                      <Upload className="h-3.5 w-3.5" />
                      {material.current_version_no ? 'Новая версия' : 'Загрузить файл'}
                    </Button>
                  </>
                )}
                <Button variant="secondary" onClick={() => setEditOpen(true)}>
                  <Pencil className="h-3.5 w-3.5" /> Изменить
                </Button>
                {isPublisher && (
                  <Button variant="secondary" onClick={() => setAudienceOpen(true)}>
                    <Users className="h-3.5 w-3.5" /> Аудитория
                  </Button>
                )}
                {material.requires_acknowledgement && (
                  <Button variant="secondary" onClick={() => setReportOpen(true)}>
                    Отчёт
                  </Button>
                )}
                {material.published_at === null && (
                  <Button
                    variant="secondary"
                    className="text-red"
                    disabled={remove.isPending}
                    onClick={() =>
                      void remove.mutateAsync(undefined as never).then(() => {
                        toast.success('Черновик удалён')
                        onClose()
                      })
                    }
                  >
                    Удалить
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose}>
            Закрыть
          </Button>
        </DialogFooter>

        {editOpen && (
          <MaterialFormDialog
            data={data}
            material={material}
            onClose={() => setEditOpen(false)}
          />
        )}
        {audienceOpen && (
          <MaterialAudienceDialog material={material} onClose={() => setAudienceOpen(false)} />
        )}
        {reportOpen && (
          <AckReportDialog material={material} onClose={() => setReportOpen(false)} />
        )}
      </DialogContent>
    </Dialog>
  )
}

// ─── Создание / правка материала ─────────────────────────────────────────────

function MaterialFormDialog({
  data,
  material,
  onClose,
}: {
  data: LibraryData
  material: LibraryMaterial | null
  onClose: () => void
}) {
  const isNew = material === null
  const [title, setTitle] = useState(material?.title ?? '')
  const [description, setDescription] = useState(material?.description ?? '')
  const [kind, setKind] = useState<'file' | 'link'>(material?.kind ?? 'file')
  const [url, setUrl] = useState(material?.url ?? '')
  const [sectionId, setSectionId] = useState(material?.section_id ?? '')
  const [requiresAck, setRequiresAck] = useState(material?.requires_acknowledgement ?? false)
  const [reAck, setReAck] = useState(material?.re_ack_on_new_version ?? false)
  const [deadlineDays, setDeadlineDays] = useState(
    material?.ack_deadline_days?.toString() ?? '',
  )
  const [reviewMonths, setReviewMonths] = useState(
    material?.review_period_months?.toString() ?? '',
  )
  const [file, setFile] = useState<File | null>(null)

  const save = useLibraryMutation(async () => {
    const body: MaterialUpsert = {
      title: title.trim(),
      description: description.trim() || null,
      section_id: sectionId || null,
      requires_acknowledgement: requiresAck,
      re_ack_on_new_version: reAck,
      ack_deadline_days: deadlineDays ? Number(deadlineDays) : null,
      review_period_months: reviewMonths ? Number(reviewMonths) : null,
      url: kind === 'link' ? url.trim() : null,
    }
    if (isNew) {
      const created = await learnApi.createMaterial({
        ...body,
        title: title.trim(),
        kind,
      })
      if (kind === 'file' && file) {
        await learnApi.uploadVersion(created.id, file)
      }
      return created
    }
    return learnApi.updateMaterial(material.id, body)
  })

  const valid =
    title.trim().length > 0 &&
    (kind === 'link' ? /^https?:\/\/\S+$/.test(url.trim()) : true)

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (!valid) return
            void save.mutateAsync(undefined as never).then(() => {
              toast.success(isNew ? 'Материал создан (черновик)' : 'Сохранено')
              onClose()
            })
          }}
        >
          <DialogHeader>
            <DialogTitle>{isNew ? 'Новый материал' : 'Изменить материал'}</DialogTitle>
            {isNew && (
              <DialogDescription>
                Материал создаётся черновиком — сотрудники увидят его после
                публикации.
              </DialogDescription>
            )}
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="mat-title">Название</Label>
              <Input
                id="mat-title"
                autoFocus={isNew}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="mat-desc">Описание</Label>
              <Textarea
                id="mat-desc"
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            {isNew && (
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setKind('file')}
                  className={cn(
                    'flex-1 rounded-lg border px-3 py-2 text-sm',
                    kind === 'file'
                      ? 'border-amber bg-amber/10 text-text'
                      : 'border-glass-border text-text3',
                  )}
                >
                  <FileText className="mx-auto mb-1 h-4 w-4" /> Файл
                </button>
                <button
                  type="button"
                  onClick={() => setKind('link')}
                  className={cn(
                    'flex-1 rounded-lg border px-3 py-2 text-sm',
                    kind === 'link'
                      ? 'border-amber bg-amber/10 text-text'
                      : 'border-glass-border text-text3',
                  )}
                >
                  <Link2 className="mx-auto mb-1 h-4 w-4" /> Ссылка
                </button>
              </div>
            )}
            {kind === 'link' && (
              <div className="space-y-1.5">
                <Label htmlFor="mat-url">URL (Google Диск, Яндекс Диск, сайт…)</Label>
                <Input
                  id="mat-url"
                  type="url"
                  placeholder="https://…"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
              </div>
            )}
            {kind === 'file' && isNew && (
              <div className="space-y-1.5">
                <Label htmlFor="mat-file">Файл (PDF, Word, Excel, PowerPoint, фото)</Label>
                <Input
                  id="mat-file"
                  type="file"
                  accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.png,.jpg,.jpeg,.txt,.csv,.md"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="mat-section">Раздел</Label>
              <Select
                id="mat-section"
                value={sectionId}
                onChange={(e) => setSectionId(e.target.value)}
              >
                <option value="">Без раздела</option>
                {data.sections.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </Select>
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-text">
              <input
                type="checkbox"
                checked={requiresAck}
                onChange={(e) => setRequiresAck(e.target.checked)}
                className="h-4 w-4 accent-[#FFB200]"
              />
              Обязательное ознакомление
            </label>
            {requiresAck && (
              <div className="grid grid-cols-2 gap-3 pl-6">
                <label className="col-span-2 flex cursor-pointer items-center gap-2 text-sm text-text">
                  <input
                    type="checkbox"
                    checked={reAck}
                    onChange={(e) => setReAck(e.target.checked)}
                    className="h-4 w-4 accent-[#FFB200]"
                  />
                  Переподтверждать при новой версии
                </label>
                <div className="space-y-1.5">
                  <Label htmlFor="mat-deadline">Дедлайн, дней</Label>
                  <Input
                    id="mat-deadline"
                    type="number"
                    min={1}
                    max={365}
                    value={deadlineDays}
                    onChange={(e) => setDeadlineDays(e.target.value)}
                  />
                </div>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="mat-review">Проверять актуальность раз в N месяцев</Label>
              <Input
                id="mat-review"
                type="number"
                min={1}
                max={60}
                placeholder="Не напоминать"
                value={reviewMonths}
                onChange={(e) => setReviewMonths(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
              Отмена
            </Button>
            <Button type="submit" disabled={!valid || save.isPending}>
              {save.isPending ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ─── Аудитория материала ─────────────────────────────────────────────────────

function MaterialAudienceDialog({
  material,
  onClose,
}: {
  material: LibraryMaterial
  onClose: () => void
}) {
  const [value, setValue] = useState<AudienceValue>({
    is_all: material.audience_id === null,
    rules: [],
  })
  const save = useLibraryMutation(() => learnApi.setMaterialAudience(material.id, value))
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Кому виден «{material.title}»</DialogTitle>
          {material.audience_id !== null && (
            <DialogDescription>
              У материала настроена аудитория. Правила ниже ЗАМЕНЯТ текущие.
            </DialogDescription>
          )}
        </DialogHeader>
        <AudiencePicker value={value} onChange={setValue} />
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            type="button"
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

// ─── Отчёт об ознакомлении ───────────────────────────────────────────────────

function AckReportDialog({
  material,
  onClose,
}: {
  material: LibraryMaterial
  onClose: () => void
}) {
  const [report, setReport] = useState<AckReport | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    learnApi
      .ackReport(material.id)
      .then(setReport)
      .catch(() => setError(true))
  }, [material.id])

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Ознакомление — «{material.title}»</DialogTitle>
          {report && (
            <DialogDescription>
              Подтвердили {report.acked} из {report.total}
            </DialogDescription>
          )}
        </DialogHeader>
        {!report && !error && <SkeletonRows rows={4} />}
        {error && <p className="text-sm text-red">Не удалось загрузить отчёт.</p>}
        {report && (
          <ul className="divide-y divide-glass-border">
            {report.rows.map((r) => (
              <li key={r.profile_id} className="flex items-center gap-2 py-2">
                <span className="min-w-0 flex-1 truncate text-sm text-text">{r.full_name}</span>
                {r.acknowledged_at ? (
                  <span className="flex items-center gap-1 text-xs text-green">
                    <Check className="h-3.5 w-3.5" /> {formatDate(r.acknowledged_at)}
                  </span>
                ) : r.overdue ? (
                  <span className="text-xs text-red">просрочено</span>
                ) : r.opened_at ? (
                  <span className="text-xs text-text3">открыл, не подтвердил</span>
                ) : (
                  <span className="text-xs text-text3">не открывал</span>
                )}
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose}>
            Закрыть
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Разделы ─────────────────────────────────────────────────────────────────

function SectionsDialog({
  sections,
  onClose,
}: {
  sections: LibrarySection[]
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const create = useLibraryMutation((title: string) => learnApi.createSection({ title }))
  const rename = useLibraryMutation((args: { id: string; title: string }) =>
    learnApi.renameSection(args.id, args.title),
  )
  const remove = useLibraryMutation((id: string) => learnApi.deleteSection(id))

  const commitRename = () => {
    const trimmed = editingTitle.trim()
    if (editingId && trimmed) {
      void rename.mutateAsync({ id: editingId, title: trimmed })
    }
    setEditingId(null)
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Разделы библиотеки</DialogTitle>
        </DialogHeader>
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
            placeholder="Новый раздел…"
          />
          <Button type="submit" disabled={!name.trim() || create.isPending}>
            <Plus className="h-4 w-4" />
          </Button>
        </form>
        <ul className="divide-y divide-glass-border">
          {sections.length === 0 && (
            <li className="py-3 text-sm text-text3">Разделов пока нет.</li>
          )}
          {sections.map((s) => (
            <li key={s.id} className="flex items-center gap-2 py-2">
              {editingId === s.id ? (
                <Input
                  autoFocus
                  className="h-8 flex-1"
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onBlur={commitRename}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      commitRename()
                    }
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                />
              ) : (
                <span className="min-w-0 flex-1 truncate text-sm text-text">{s.title}</span>
              )}
              <button
                type="button"
                title="Переименовать"
                className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text"
                onClick={() => {
                  setEditingId(s.id)
                  setEditingTitle(s.title)
                }}
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                title="Удалить (только пустой)"
                className="rounded p-1.5 text-text3 hover:bg-glass hover:text-red"
                onClick={() => void remove.mutateAsync(s.id)}
              >
                <Archive className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose}>
            Закрыть
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
