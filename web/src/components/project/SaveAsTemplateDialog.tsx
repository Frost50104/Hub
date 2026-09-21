import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { DateField } from '@/components/ui/DateField'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { useSaveAsTemplate, useSaveAsTemplatePreview } from '@/hooks/useProjectTemplates'
import { formatBytes } from '@/lib/attachmentTypes'
import { droppedSummary, previewWarnings } from '@/lib/projectTemplates'
import { type Project } from '@/lib/projects'
import { plural } from '@/lib/typography'

/**
 * «Сохранить как шаблон» (0060) — из «О проекте» → «Настройки проекта».
 *
 * Проект остаётся как есть; копия уходит в общую библиотеку. Точку отсчёта
 * предлагает сервер — самую раннюю дату задачи (не дату создания проекта: у
 * перенесённых из WEEEK это день импорта). До нажатия диалог называет, что НЕ
 * попадёт: архивные задачи, прошлые шаги повтора, уволенных — и что сам
 * сохраняющий в состав шаблона не войдёт (решение владельца).
 */
export function SaveAsTemplateDialog({
  project,
  open,
  onOpenChange,
}: {
  project: Project
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const nav = useNavigate()
  const preview = useSaveAsTemplatePreview(project.id, open)
  const save = useSaveAsTemplate(project.id)
  const [name, setName] = useState('')
  const [anchor, setAnchor] = useState('')
  const [includeMembers, setIncludeMembers] = useState(true)
  const [includeAttachments, setIncludeAttachments] = useState(true)

  useEffect(() => {
    if (!open) return
    setName(`${project.name} — шаблон`.slice(0, 255))
    setAnchor('')
    setIncludeMembers(true)
    setIncludeAttachments(true)
  }, [open, project.name])

  // Точка отсчёта приходит с предпросмотром — подставляем, пока человек сам
  // её не трогал.
  useEffect(() => {
    if (open && preview.data && !anchor) setAnchor(preview.data.suggested_anchor_on)
  }, [open, preview.data, anchor])

  const data = preview.data
  const blocked =
    !data || data.too_big || (!data.disk_ok && includeAttachments) || !name.trim()

  const submit = async () => {
    if (blocked) return
    try {
      const template = await save.mutateAsync({
        name: name.trim(),
        anchor_on: anchor || undefined,
        include_members: includeMembers,
        include_attachments: includeAttachments,
      })
      toast.success(`Шаблон «${template.name}» сохранён`, {
        description: 'Его увидят все, кто создаёт проекты.',
      })
      onOpenChange(false)
      nav(`/projects/${template.id}`)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  const total = data ? data.tasks + data.subtasks : 0
  const dropped = data ? droppedSummary(data.dropped) : null
  const warnings = data
    ? previewWarnings(data, { includeAttachments }).filter(
        // Шаблон не шлёт уведомлений: просрочка и напоминания — про проект из
        // него, их считает диалог создания проекта (на проде «142 задачи сразу
        // будут просрочены» здесь пугало зря).
        (w) => w.kind !== 'overdue' && w.kind !== 'due_soon',
      )
    : []

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={(v) => !save.isPending && onOpenChange(v)}
      title="Сохранить как шаблон"
      description={`Шаблон увидят все, кто создаёт проекты. Проект «${project.name}» останется как есть.`}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={save.isPending}>
            Отмена
          </Button>
          <Button onClick={() => void submit()} disabled={save.isPending || blocked}>
            {save.isPending ? 'Сохраняем…' : 'Сохранить шаблон'}
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="save-template-name">Название шаблона</Label>
          <Input
            id="save-template-name"
            maxLength={255}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="save-template-anchor">Точка отсчёта</Label>
          <DateField id="save-template-anchor" value={anchor} onChange={setAnchor} />
          <p className="text-[13px] text-text3">
            Самая ранняя дата задачи. От неё считаются сдвиги сроков в новых проектах.
          </p>
        </div>

        {preview.isLoading && <p className="text-[14px] text-text2">Считаем, что попадёт в шаблон…</p>}

        {data && (
          <>
            {(data.members > 0 || data.attachments > 0) && (
              <div className="flex flex-col gap-2">
                {data.members > 0 && (
                  <label className="flex min-h-11 items-center gap-2.5 text-[14px] text-text lg:min-h-0">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-amber"
                      checked={includeMembers}
                      onChange={(e) => setIncludeMembers(e.target.checked)}
                    />
                    Участники ({data.members})
                  </label>
                )}
                {data.attachments > 0 && (
                  <label className="flex min-h-11 items-center gap-2.5 text-[14px] text-text lg:min-h-0">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-amber"
                      checked={includeAttachments}
                      onChange={(e) => setIncludeAttachments(e.target.checked)}
                    />
                    Вложения ({data.attachments} · {formatBytes(data.attachment_bytes)})
                  </label>
                )}
              </div>
            )}
            <div className="flex flex-col gap-1.5 rounded-xl border border-glass-border bg-tint p-4 text-[13px] leading-[1.45] text-text2">
              <span className="text-[14px] text-text">
                Скопируется {plural(total, 'задача', 'задачи', 'задач')}.
              </span>
              {dropped && <span>{dropped}</span>}
              <span>Выполненные задачи станут невыполненными, комментарии не копируются.</span>
              <span>Вас в составе шаблона не будет — добавьте себя вручную, если нужно.</span>
            </div>
            {warnings.length > 0 && (
              <ul className="flex flex-col gap-1.5 text-[13px] leading-[1.45] text-text2">
                {warnings.map((w) => (
                  <li key={w.text}>{w.text}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </form>
    </ResponsiveDialog>
  )
}
