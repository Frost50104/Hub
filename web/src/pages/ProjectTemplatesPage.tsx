import { ChevronLeft, Layers, Plus, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { CreateProjectDialog } from '@/components/project/CreateProjectDialog'
import { NewTemplateDialog } from '@/components/project/NewTemplateDialog'
import { ProjectKeyChip } from '@/components/project/ProjectKeyChip'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { Input } from '@/components/ui/Input'
import { ListRow } from '@/components/ui/ListRow'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { Switch } from '@/components/ui/Switch'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import {
  useSetTemplatesEnabled,
  useTemplateSettings,
  useTemplates,
} from '@/hooks/useProjectTemplates'
import { dataAgeLabel } from '@/lib/dates'
import {
  TEMPLATE_FILTER_FROM,
  templateRowMeta,
  templatesEnabled,
  type TemplateListItem,
} from '@/lib/projectTemplates'
import { filterOptions } from '@/lib/selectOptions'
import { plural } from '@/lib/typography'

/**
 * Библиотека шаблонов проектов (0060) — `/projects/templates`.
 *
 * Строка открывает шаблон (обычная страница проекта с плашкой), «Использовать»
 * — диалог «Новый проект» в режиме «По шаблону». Тумблер модуля — здесь, у
 * hub-admin: «Управление» — пространство «Обучения», а шаблоны живут в трекере.
 */
export function ProjectTemplatesPage() {
  const isDesktop = useIsDesktop()
  const me = useMe().data
  const enabled = templatesEnabled(me)
  const isAdmin = me?.features?.project_templates_admin === true
  // Видят библиотеку только те, кто создаёт проекты (сервер отвечает 403
  // остальным). Без этого наблюдатель по прямой ссылке получал «Не удалось
  // загрузить шаблоны» с кнопкой «Повторить», которая не поможет никогда.
  const canView = enabled && me?.can_create_projects === true
  const templates = useTemplates(canView)
  const settings = useTemplateSettings(isAdmin)
  const setEnabled = useSetTemplatesEnabled()
  const [query, setQuery] = useState('')
  const [useTemplateId, setUseTemplateId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [newOpen, setNewOpen] = useState(false)

  const all = useMemo(() => templates.data ?? [], [templates.data])
  const rows = useMemo(() => {
    if (!query.trim()) return all
    const hits = new Set(
      filterOptions(
        all.map((t) => ({ value: t.id, label: t.name, meta: `${t.key} ${t.author_name ?? ''}` })),
        query,
      ).map((o) => o.value),
    )
    return all.filter((t) => hits.has(t.id))
  }, [all, query])

  const canCreate = enabled && me?.can_create_projects === true
  const openUse = (id: string) => {
    setUseTemplateId(id)
    setCreateOpen(true)
  }

  const toggle = isAdmin && settings.data && (
    <label className="flex min-h-11 shrink-0 items-center gap-2.5 whitespace-nowrap text-[13px] text-text2">
      <Switch
        checked={settings.data.enabled}
        disabled={setEnabled.isPending}
        onCheckedChange={(v) => setEnabled.mutate(v)}
        aria-label="Шаблоны проектов включены для компании"
      />
      Включены для компании
    </label>
  )

  const newButton = canCreate && (
    <Button size={isDesktop ? 'md' : 'sm'} onClick={() => setNewOpen(true)} className="shrink-0 whitespace-nowrap">
      <Plus className="h-4 w-4" strokeWidth={2} />
      Новый шаблон
    </Button>
  )

  let body: React.ReactNode
  if (!enabled) {
    body = (
      <EmptyState
        layout="card"
        icon={<Layers className="h-6 w-6" />}
        title="Шаблоны выключены"
        text={
          isAdmin
            ? 'Включите их тумблером выше — библиотека появится у всех, кто создаёт проекты.'
            : 'Администратор Hub ещё не включил шаблоны проектов для компании.'
        }
      />
    )
  } else if (!canView) {
    body = (
      <EmptyState
        layout="card"
        icon={<Layers className="h-6 w-6" />}
        title="Шаблоны доступны не всем"
        text="Библиотеку шаблонов видят те, кто создаёт проекты: администраторы Hub, офис, ТУ и франчайзи."
      />
    )
  } else if (templates.isLoading) {
    body = <SkeletonRows rows={4} />
  } else if (templates.isError) {
    body = (
      <EmptyState
        tone="error"
        layout="card"
        title="Не удалось загрузить шаблоны"
        text="Проверьте соединение и попробуйте ещё раз."
        meta={dataAgeLabel(templates.dataUpdatedAt)}
        cta="Повторить"
        onCta={() => void templates.refetch()}
      />
    )
  } else if (all.length === 0) {
    body = (
      <EmptyState
        layout="card"
        icon={<Layers className="h-6 w-6" />}
        title="Шаблонов пока нет"
        text="Сохраните готовый проект как шаблон: «О проекте» → «Настройки» → «Сохранить как шаблон». Или соберите заготовку с нуля."
        cta={canCreate ? 'Новый шаблон' : undefined}
        onCta={canCreate ? () => setNewOpen(true) : undefined}
      />
    )
  } else {
    body = (
      <div className="flex flex-col gap-3">
        {all.length >= TEMPLATE_FILTER_FROM && (
          <div className="relative max-w-[420px]">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text3"
              strokeWidth={1.8}
            />
            <Input
              aria-label="Найти шаблон"
              placeholder="Найти шаблон"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-9"
            />
          </div>
        )}
        <p className="text-[13px] text-text3">
          {query.trim()
            ? `Найдено: ${rows.length} из ${all.length}`
            : plural(all.length, 'шаблон', 'шаблона', 'шаблонов')}
        </p>
        {isDesktop ? (
          <div className="flex flex-col">
            {rows.map((t) => (
              // Строка НЕ кликабельна целиком: `ListRow` с onClick — это
              // div role=button со своим keydown, и Enter на «Использовать»
              // всплывал бы в строку и открывал шаблон вместо диалога (а кнопка
              // в кнопке ещё и невалидна). Открывает шаблон ссылка-название.
              <ListRow
                key={t.id}
                lead={<ProjectKeyChip project={{ ...t, is_favorite: false }} size="md" />}
                title={
                  <Link
                    to={`/projects/${t.id}`}
                    className="min-w-0 truncate rounded-sm hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                  >
                    {t.name}
                  </Link>
                }
                context={<span className="min-w-0 truncate">{templateRowMeta(t)}</span>}
                trailing={
                  <Button
                    size="sm"
                    variant="secondary"
                    className="whitespace-nowrap"
                    onClick={() => openUse(t.id)}
                  >
                    Использовать
                  </Button>
                }
              />
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-2.5">
            {rows.map((t) => (
              <MobileTemplateCard key={t.id} item={t} onUse={() => openUse(t.id)} />
            ))}
          </div>
        )}
      </div>
    )
  }

  const dialogs = (
    <>
      <CreateProjectDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        initialTemplateId={useTemplateId}
      />
      <NewTemplateDialog open={newOpen} onOpenChange={setNewOpen} />
    </>
  )

  if (!isDesktop) {
    return (
      <div className="flex flex-col pb-6">
        <MobilePageHeader
          topSlot={
            <Link
              to="/projects"
              className="-ml-1 inline-flex min-h-11 items-center gap-1 text-[14px] text-text2"
            >
              <ChevronLeft className="h-4 w-4" strokeWidth={1.8} />
              Проекты
            </Link>
          }
          title="Шаблоны"
          trailing={newButton || undefined}
          className="pb-2"
        />
        <div className="flex flex-col gap-3 px-4">
          {toggle}
          {body}
        </div>
        {dialogs}
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-[1040px] flex-col gap-[18px] px-6 pb-10 pt-7">
      <header className="flex min-w-0 flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 max-w-[640px]">
          <h1 className="font-display text-[24px] font-bold leading-[1.2] text-text">
            Шаблоны проектов
          </h1>
          <p className="mt-[5px] text-[15px] leading-[1.5] text-text2">
            Колонки, метки, задачи со сроками и люди — одной заготовкой. Проект по шаблону
            получает все задачи, а сроки сдвигаются к дате старта.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-5">
          {toggle}
          {newButton}
        </div>
      </header>
      {body}
      {dialogs}
    </div>
  )
}

function MobileTemplateCard({ item, onUse }: { item: TemplateListItem; onUse: () => void }) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-glass-border bg-tint p-4">
      <Link to={`/projects/${item.id}`} className="flex min-w-0 items-center gap-3">
        <ProjectKeyChip project={{ ...item, is_favorite: false }} size="md" />
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate text-[15px] font-semibold text-text">{item.name}</span>
          <span className="text-[13px] leading-[1.4] text-text2">{templateRowMeta(item)}</span>
        </span>
      </Link>
      <Button variant="secondary" className="min-h-11 w-full" onClick={onUse}>
        Создать проект по шаблону
      </Button>
    </div>
  )
}
