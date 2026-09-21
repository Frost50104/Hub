import { CalendarDays, Info } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { CreateProjectDialog } from '@/components/project/CreateProjectDialog'
import { Button } from '@/components/ui/Button'
import { DateField } from '@/components/ui/DateField'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { useSetTemplateAnchor } from '@/hooks/useProjectTemplates'
import { longDay, templatePageGate } from '@/lib/projectTemplates'
import { type Project } from '@/lib/projects'
import { todayKey } from '@/lib/taskDates'

/**
 * Плашка «Это шаблон» над страницей шаблона (0060) — на месте полосы
 * «Только чтение». Говорит главное про шаблон до первого клика: даты считаются
 * от точки отсчёта, уведомлений нет, задачи здесь не выполняются. Кнопки — в
 * одну строку и не сжимаются (ревью макета 21.09).
 */
export function TemplateBanner({ project }: { project: Project }) {
  const gate = templatePageGate(project)
  const [anchorOpen, setAnchorOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const anchor = project.template_anchor_on

  return (
    <section className="flex shrink-0 flex-col gap-3 border-b border-hair bg-tint px-4 py-3 lg:flex-row lg:items-center lg:gap-4 lg:px-6">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <Info className="mt-0.5 h-5 w-5 shrink-0 text-blue-deep" strokeWidth={1.8} />
        <div className="min-w-0">
          <p className="text-[14px] font-semibold text-text">Это шаблон — заготовка, а не работа</p>
          <p className="mt-0.5 text-[14px] leading-[1.45] text-text2">
            {anchor
              ? `Даты задач считаются от ${longDay(anchor)} и при создании проекта сдвинутся к дате старта.`
              : 'Даты задач сдвинутся к дате старта проекта.'}{' '}
            Уведомлений шаблон не шлёт, задачи здесь не выполняются.
            {!project.can_edit && ' Править шаблон могут его автор и администраторы Hub.'}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 lg:shrink-0 lg:flex-nowrap">
        {gate.canEditAnchor && (
          <Button
            variant="secondary"
            size="sm"
            className="shrink-0 whitespace-nowrap"
            onClick={() => setAnchorOpen(true)}
          >
            <CalendarDays className="h-4 w-4" strokeWidth={1.8} />
            Изменить точку отсчёта
          </Button>
        )}
        <Button size="sm" className="shrink-0 whitespace-nowrap" onClick={() => setCreateOpen(true)}>
          Создать проект по шаблону
        </Button>
      </div>
      <AnchorDialog
        project={project}
        open={anchorOpen}
        onOpenChange={setAnchorOpen}
      />
      <CreateProjectDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        initialTemplateId={project.id}
      />
    </section>
  )
}

function AnchorDialog({
  project,
  open,
  onOpenChange,
}: {
  project: Project
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const setAnchor = useSetTemplateAnchor(project.id)
  const [value, setValue] = useState(project.template_anchor_on ?? todayKey())

  useEffect(() => {
    if (open) setValue(project.template_anchor_on ?? todayKey())
  }, [open, project.template_anchor_on])

  const save = async () => {
    if (!value) return
    try {
      await setAnchor.mutateAsync(value)
      toast.success(`Точка отсчёта — ${longDay(value)}`)
      onOpenChange(false)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={(v) => !setAnchor.isPending && onOpenChange(v)}
      title="Точка отсчёта"
      description="Сроки задач шаблона считаются от этой даты. Сами даты задач не двигаются — меняется только то, насколько они сдвинутся в новом проекте."
      desktopWidth={480}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={setAnchor.isPending}>
            Отмена
          </Button>
          <Button onClick={() => void save()} disabled={setAnchor.isPending || !value}>
            {setAnchor.isPending ? 'Сохраняем…' : 'Сохранить'}
          </Button>
        </>
      }
    >
      <div className="space-y-1.5">
        <Label htmlFor="template-anchor">Дата</Label>
        <DateField id="template-anchor" value={value} onChange={setValue} />
      </div>
    </ResponsiveDialog>
  )
}
