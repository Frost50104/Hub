import { AlertTriangle, Bell } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { DateField } from '@/components/ui/DateField'
import { Input, Textarea } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SearchableSelect } from '@/components/ui/SearchableSelect'
import { SegmentGroup } from '@/components/ui/SegmentGroup'
import { Select } from '@/components/ui/Select'
import { useMe } from '@/hooks/useMe'
import {
  useCreateProjectFromTemplate,
  useTemplatePreview,
  useTemplates,
} from '@/hooks/useProjectTemplates'
import { useCreateProject, useProjectFolders } from '@/hooks/useProjects'
import { cn } from '@/lib/cn'
import {
  fromTemplateReady,
  previewFacts,
  previewNotifyLine,
  previewWarnings,
  reportDescription,
  templateModeAvailable,
  type PreviewWarning,
} from '@/lib/projectTemplates'
import { todayKey } from '@/lib/taskDates'
import { plural } from '@/lib/typography'

/** Потолки — как у `ProjectCreate` на сервере. */
const NAME_MAX = 255
const DESCRIPTION_MAX = 4000

type Mode = 'blank' | 'template'

const WARNING_TONE: Record<PreviewWarning['tone'], string> = {
  red: 'text-red',
  amber: 'text-amber',
  blue: 'text-blue-deep',
}

/**
 * Единственный диалог «Новый проект» — для сайдбара, шторки FAB, `/projects`,
 * библиотеки шаблонов и плашки шаблона. До 21.09 это были три копии, и
 * разошлись они уже в поведении. Режим «По шаблону» (0060) — при включённом
 * модуле: шаблон, название, дата старта, папка, предпросмотр того, что
 * будет создано, и предупреждения ДО нажатия — считает их сервер тем же
 * кодом, что и копирует.
 */
export function CreateProjectDialog({
  open,
  onOpenChange,
  initialTemplateId = null,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  /** Открыть сразу в режиме «По шаблону» с этим шаблоном. */
  initialTemplateId?: string | null
}) {
  const me = useMe().data
  const withTemplates = templateModeAvailable(me)
  const nav = useNavigate()
  const create = useCreateProject()
  const createFromTemplate = useCreateProjectFromTemplate()

  const [mode, setMode] = useState<Mode>('blank')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [templateId, setTemplateId] = useState<string | null>(null)
  const [startOn, setStartOn] = useState(todayKey())
  const [folderId, setFolderId] = useState('')
  const [includeMembers, setIncludeMembers] = useState(true)
  const [includeAttachments, setIncludeAttachments] = useState(true)

  // Состояние формы — при каждом открытии, а не в useState: диалог живёт
  // смонтированным между открытиями, а шаблон приходит пропом.
  useEffect(() => {
    if (!open) return
    setMode(initialTemplateId && withTemplates ? 'template' : 'blank')
    setTemplateId(initialTemplateId)
    setName('')
    setDescription('')
    setStartOn(todayKey())
    setFolderId('')
    setIncludeMembers(true)
    setIncludeAttachments(true)
  }, [open, initialTemplateId, withTemplates])

  const templateMode = mode === 'template' && withTemplates
  const templates = useTemplates(open && templateMode)
  const folders = useProjectFolders()
  const preview = useTemplatePreview(open && templateMode ? templateId : null, startOn || null)

  const templateOptions = useMemo(
    () =>
      (templates.data ?? []).map((t) => ({
        value: t.id,
        label: t.name,
        meta: plural(t.task_count, 'задача', 'задачи', 'задач'),
      })),
    [templates.data],
  )
  const folderList = folders.data?.folders ?? []
  const busy = create.isPending || createFromTemplate.isPending

  const submitBlank = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    try {
      const project = await create.mutateAsync({
        name: trimmed,
        description: description.trim() || undefined,
      })
      toast.success(`Проект ${project.key} создан`)
      onOpenChange(false)
      nav(`/projects/${project.id}`)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  const submitTemplate = async () => {
    if (!templateId || !fromTemplateReady({ name, templateId, includeAttachments }, preview.data)) {
      return
    }
    try {
      const { project, report } = await createFromTemplate.mutateAsync({
        templateId,
        body: {
          name: name.trim(),
          start_on: startOn || undefined,
          folder_id: folderId || null,
          include_members: includeMembers,
          include_attachments: includeAttachments,
        },
      })
      toast.success(`Проект «${project.name}» создан`, { description: reportDescription(report) })
      onOpenChange(false)
      nav(`/projects/${project.id}`)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  const canSubmit = templateMode
    ? fromTemplateReady({ name, templateId, includeAttachments }, preview.data)
    : name.trim().length > 0
  const submit = () => void (templateMode ? submitTemplate() : submitBlank())

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={(v) => !busy && onOpenChange(v)}
      title="Новый проект"
      description={
        templateMode
          ? 'Задачи, колонки, метки и люди придут из шаблона, сроки сдвинутся к дате старта.'
          : 'Короткий ключ для задач (HUB-123) подберётся автоматически из названия.'
      }
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Отмена
          </Button>
          <Button onClick={submit} disabled={busy || !canSubmit}>
            {busy ? 'Создаём…' : templateMode ? 'Создать проект' : 'Создать'}
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit && !busy) submit()
        }}
      >
        {withTemplates && (
          <SegmentGroup<Mode>
            ariaLabel="Как создать проект"
            fullWidth
            size="md"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'blank', label: 'Пустой' },
              { value: 'template', label: 'По шаблону' },
            ]}
          />
        )}

        {templateMode && (
          <div className="space-y-1.5">
            <Label htmlFor="create-project-template">Шаблон</Label>
            <SearchableSelect
              id="create-project-template"
              value={templateId}
              onChange={setTemplateId}
              options={templateOptions}
              clearLabel={null}
              placeholder={templates.isLoading ? 'Загружаем шаблоны…' : 'Выберите шаблон'}
              searchPlaceholder="Найти шаблон"
              emptyText="Шаблонов пока нет"
              sheetTitle="Шаблон"
            />
          </div>
        )}

        <div className="space-y-1.5">
          <Label htmlFor="create-project-name">Название</Label>
          <Input
            id="create-project-name"
            placeholder={templateMode ? 'Невский, 10' : 'Маркетинг'}
            autoFocus={!templateMode}
            maxLength={NAME_MAX}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        {!templateMode && (
          <div className="space-y-1.5">
            <Label htmlFor="create-project-desc">Описание (опционально)</Label>
            <Textarea
              id="create-project-desc"
              rows={2}
              maxLength={DESCRIPTION_MAX}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        )}

        {templateMode && (
          <div className={cn('grid gap-4', folderList.length > 0 && 'lg:grid-cols-2')}>
            <div className="min-w-0 space-y-1.5">
              <Label htmlFor="create-project-start">Дата старта</Label>
              <DateField id="create-project-start" value={startOn} onChange={setStartOn} />
            </div>
            {folderList.length > 0 && (
              <div className="min-w-0 space-y-1.5">
                <Label htmlFor="create-project-folder">Папка</Label>
                <Select
                  id="create-project-folder"
                  value={folderId}
                  onChange={(e) => setFolderId(e.target.value)}
                >
                  <option value="">Без папки</option>
                  {folderList.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
          </div>
        )}

        {templateMode && templateId && (
          <TemplatePreviewBlock
            loading={preview.isLoading}
            data={preview.data}
            includeMembers={includeMembers}
            onIncludeMembers={setIncludeMembers}
            includeAttachments={includeAttachments}
            onIncludeAttachments={setIncludeAttachments}
          />
        )}
      </form>
    </ResponsiveDialog>
  )
}

function TemplatePreviewBlock({
  loading,
  data,
  includeMembers,
  onIncludeMembers,
  includeAttachments,
  onIncludeAttachments,
}: {
  loading: boolean
  data: ReturnType<typeof useTemplatePreview>['data']
  includeMembers: boolean
  onIncludeMembers: (v: boolean) => void
  includeAttachments: boolean
  onIncludeAttachments: (v: boolean) => void
}) {
  if (loading || !data) {
    return <p className="text-[14px] text-text2">Считаем, что будет создано…</p>
  }
  const notify = previewNotifyLine(data)
  const warnings = previewWarnings(data, { includeAttachments })
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 rounded-xl border border-glass-border bg-tint p-4">
        <p className="text-[12px] font-bold uppercase tracking-[0.08em] text-text3">Будет создано</p>
        <ul className="grid gap-x-4 gap-y-1.5 text-[14px] text-text sm:grid-cols-2">
          {previewFacts(data).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        {notify && <p className="text-[14px] text-text2">{notify}</p>}
        {(data.members > 0 || data.attachments > 0) && (
          <div className="flex flex-col gap-2 pt-1">
            {data.members > 0 && (
              <label className="flex min-h-11 items-center gap-2.5 text-[14px] text-text lg:min-h-0">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-amber"
                  checked={includeMembers}
                  onChange={(e) => onIncludeMembers(e.target.checked)}
                />
                Участники шаблона ({data.members})
              </label>
            )}
            {data.attachments > 0 && (
              <label className="flex min-h-11 items-center gap-2.5 text-[14px] text-text lg:min-h-0">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-amber"
                  checked={includeAttachments}
                  onChange={(e) => onIncludeAttachments(e.target.checked)}
                />
                Вложения ({data.attachments})
              </label>
            )}
          </div>
        )}
      </div>
      {warnings.length > 0 && (
        <ul className="flex flex-col gap-2">
          {warnings.map((w) => (
            <li key={w.text} className="flex items-start gap-2.5 text-[13px] leading-[1.45] text-text2">
              {w.tone === 'blue' ? (
                <Bell className={cn('mt-0.5 h-4 w-4 shrink-0', WARNING_TONE[w.tone])} strokeWidth={1.8} />
              ) : (
                <AlertTriangle
                  className={cn('mt-0.5 h-4 w-4 shrink-0', WARNING_TONE[w.tone])}
                  strokeWidth={1.8}
                />
              )}
              <span>{w.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
