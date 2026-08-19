import {
  Archive,
  Check,
  ChevronRight,
  CircleAlert,
  ExternalLink,
  FileText,
  FolderCog,
  Link2,
  Pencil,
  Plus,
  Search,
  Send,
  Upload,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AudiencePicker, useAudienceDraft } from '@/components/learn/AudiencePicker'
import { QueryError } from '@/components/QueryError'
import { Badge } from '@/components/ui/Badge'
import { MetaLine } from '@/components/ui/MetaLine'
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
import { cn } from '@/lib/cn'
import { nbsp, plural } from '@/lib/typography'
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

/** Расширение файла для плитки: тип не кодируется цветом — он написан текстом. */
function extLabel(m: LibraryMaterial): string {
  if (m.kind === 'link') return ''
  const name = m.current_version?.file_name ?? ''
  const dot = name.lastIndexOf('.')
  const ext = dot > 0 ? name.slice(dot + 1) : ''
  return ext.slice(0, 4).toUpperCase() || 'ФАЙЛ'
}

function materialMeta(m: LibraryMaterial): string[] {
  return [
    m.kind === 'link'
      ? 'внешняя ссылка'
      : m.current_version
        ? `v${m.current_version.version_no} · ${formatSize(m.current_version.size_bytes)}`
        : 'файл не загружен',
    m.owner_name ? `владелец: ${m.owner_name}` : '',
    `обновлён ${formatDate(m.updated_at)}`,
  ].filter(Boolean)
}

/** «до 20 августа · осталось 3 дня» — срок ознакомления лично для меня. */
function ackDeadlineText(m: LibraryMaterial): string {
  if (!m.ack_deadline_at) return 'Требует ознакомления'
  const due = new Date(m.ack_deadline_at)
  const when = due.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
  const days = Math.ceil((due.getTime() - Date.now()) / 86_400_000)
  if (days < 0) return `Просрочено · срок был ${when}`
  if (days === 0) return `Ознакомиться до ${when} · сегодня последний день`
  return `Ознакомиться до ${when} · осталось ${plural(days, 'день', 'дня', 'дней')}`
}

function ExtTile({ material, accent }: { material: LibraryMaterial; accent?: boolean }) {
  return (
    <span
      className={cn(
        'flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] border font-display text-[9px] font-bold tracking-[0.02em]',
        accent
          ? 'border-transparent bg-amber text-on-amber'
          : 'border-hair bg-surface text-text2',
      )}
    >
      {material.kind === 'link' ? <Link2 className="h-[18px] w-[18px]" /> : extLabel(material)}
    </span>
  )
}

export function LearnLibraryPage() {
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState('')
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

  // `?? []` каждый раз создаёт новый массив и обнуляет мемоизацию ниже.
  const sections = useMemo(() => data?.sections ?? [], [data])
  const sectionTitle = useMemo(
    () => new Map(sections.map((s) => [s.id, s.title])),
    [sections],
  )

  const all = useMemo(() => data?.materials ?? [], [data])

  // Поиск и раздел фильтруют ОБА блока: иначе над результатами поиска висели
  // бы нерелевантные амбер-карточки просто потому, что они срочные.
  const matching = useMemo(() => {
    const q = query.trim().toLowerCase()
    return all
      .filter((m) => (sectionFilter ? m.section_id === sectionFilter : true))
      .filter((m) => {
        if (!q) return true
        const section = m.section_id ? (sectionTitle.get(m.section_id) ?? '') : ''
        return m.title.toLowerCase().includes(q) || section.toLowerCase().includes(q)
      })
  }, [all, query, sectionFilter, sectionTitle])

  // Требующие ознакомления и общий список — подмножества одного массива:
  // документ не может встретиться дважды на одном экране.
  const urgent = useMemo(() => matching.filter((m) => m.ack_pending), [matching])
  const materials = useMemo(() => matching.filter((m) => !m.ack_pending), [matching])

  const searching = query.trim().length > 0 || sectionFilter !== ''
  const found = searching
    ? `${matching.length} из ${all.length}`
    : plural(all.length, 'документ', 'документа', 'документов')

  return (
    <div className="mx-auto max-w-[680px]">
      <header className="flex items-end justify-between gap-3 px-5 pt-11">
        <div className="min-w-0">
          <p className="mb-1 text-xs leading-[1.35] text-text2">{nbsp(found)}</p>
          <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
            Библиотека
          </h1>
        </div>
        {canManage && (
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
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
      </header>

      {/* Поле 48px, input растянут на всю высоту строки: иначе фокус ловит 23px. */}
      <div className="px-5 pt-4">
        <div className="flex min-h-[48px] items-center gap-2.5 rounded-xl border border-glass-border bg-tint px-3.5">
          <Search className="h-[18px] w-[18px] shrink-0 text-text2" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Название или раздел"
            aria-label="Поиск по библиотеке"
            className="min-w-0 flex-1 self-stretch border-none bg-transparent text-[16px] text-text outline-none placeholder:text-text2"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Очистить"
              className="-mr-2.5 flex h-11 w-11 shrink-0 items-center justify-center text-text2 hover:text-text"
            >
              <X className="h-[18px] w-[18px]" />
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-7 px-5 pb-8 pt-6">
        {probe.isLoading && <SkeletonRows rows={6} rowClassName="h-[56px]" />}
        {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}

        {urgent.length > 0 && (
          <section className="flex flex-col gap-2.5">
            <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.09em] text-text2">
              <CircleAlert className="h-[15px] w-[15px]" strokeWidth={2.2} />
              Требуют ознакомления
            </p>
            {urgent.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => setOpened(m.id)}
                className="flex min-h-[56px] items-center gap-3 rounded-[14px] border border-amber/40 bg-amber/[0.06] px-3.5 py-3 text-left"
              >
                <ExtTile material={m} accent />
                <span className="min-w-0 flex-1">
                  <span className="block text-[16px] font-semibold leading-[1.35] text-text">
                    {m.title}
                  </span>
                  <span className="mt-0.5 block text-[13px] text-text">
                    {nbsp(ackDeadlineText(m))}
                  </span>
                </span>
                <ChevronRight className="h-[18px] w-[18px] shrink-0 text-text2" />
              </button>
            ))}
          </section>
        )}

        {sections.length > 0 && (
          <section className="flex flex-col gap-2.5">
            <p className="text-xs font-bold uppercase tracking-[0.09em] text-text2">
              Разделы
            </p>
            <div className="flex flex-wrap gap-2">
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
          </section>
        )}

        <section className="flex flex-col gap-2.5">
          <p className="text-xs font-bold uppercase tracking-[0.09em] text-text2">
            Документы
          </p>

          {data && materials.length === 0 && urgent.length === 0 && (
            <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface text-text2">
                <Search className="h-[26px] w-[26px]" strokeWidth={1.7} />
              </span>
              <p className="text-[16px] leading-[1.6] text-text2 [text-wrap:pretty]">
                {searching
                  ? 'Ничего не нашлось. Попробуйте короче — например «кофемашина» вместо полного названия.'
                  : 'В библиотеке пока пусто.'}
              </p>
              {searching && (
                <button
                  type="button"
                  onClick={() => {
                    setQuery('')
                    setSectionFilter('')
                  }}
                  className="inline-flex min-h-[44px] items-center justify-center rounded-[10px] border border-glass-border px-[18px] text-[15px] font-semibold text-text"
                >
                  Сбросить поиск
                </button>
              )}
            </div>
          )}

          <div className="flex flex-col gap-2">
            {materials.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => setOpened(m.id)}
                className="flex min-h-[56px] items-center gap-3 rounded-[14px] border border-hair px-3 py-2.5 text-left transition-colors hover:border-amber/40"
              >
                <ExtTile material={m} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] font-semibold leading-[1.35] text-text lg:text-[16px]">
                    {m.title}
                  </span>
                  <MetaLine
                    className="mt-0.5 text-[13px] text-text2 lg:text-sm"
                    items={materialMeta(m)}
                  />
                </span>
                {canManage && m.status !== 'published' && (
                  <Badge variant="secondary">{CONTENT_STATUS_LABEL[m.status]}</Badge>
                )}
                {m.requires_acknowledgement && m.acked_by_me && (
                  <Check className="h-4 w-4 shrink-0 text-green" />
                )}
                {m.kind === 'link' && (
                  <ExternalLink className="h-4 w-4 shrink-0 text-text2" />
                )}
              </button>
            ))}
          </div>
        </section>
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
        <MaterialFormDialog data={data} material={null} onClose={() => setCreateOpen(false)} />
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
        // 44px — тап-таргет, а не декоративная высота чипа.
        'inline-flex min-h-[44px] items-center whitespace-nowrap rounded-full border px-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
        active
          ? 'border-amber bg-amber text-on-amber'
          : 'border-hair text-text2 hover:text-text',
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
            {material.requires_acknowledgement &&
              material.status === 'published' &&
              !material.acked_by_me &&
              !openedLocally && (
                <p className="w-full text-[13px] leading-[1.45] text-text2">
                  Отметка станет доступна, когда вы откроете документ.
                </p>
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
  const audience = useAudienceDraft(material.audience_id)
  const { value, setValue } = audience
  const save = useLibraryMutation(() => learnApi.setMaterialAudience(material.id, value))
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Кому виден «{material.title}»</DialogTitle>
        </DialogHeader>
        {audience.loading ? (
          <SkeletonRows rows={3} />
        ) : (
          <>
            {audience.failed && (
              <p className="text-sm text-red">
                Не удалось загрузить текущие правила — сохранение перезапишет их.
              </p>
            )}
            <AudiencePicker
              value={value}
              onChange={setValue}
              extraLabels={audience.extraLabels}
            />
          </>
        )}
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            type="button"
            disabled={save.isPending || !audience.ready}
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
