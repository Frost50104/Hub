import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { DateField } from '@/components/ui/DateField'
import { Input, Textarea } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { useCreateTemplate } from '@/hooks/useProjectTemplates'
import { todayKey } from '@/lib/taskDates'

/**
 * «Новый шаблон» с нуля. Точка отсчёта по умолчанию — сегодня: от неё
 * считаются сроки задач, которые автор расставит в шаблоне, и при создании
 * проекта они сдвинутся к дате старта. После создания — на страницу шаблона,
 * где он правится как обычный проект.
 */
export function NewTemplateDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const create = useCreateTemplate()
  const nav = useNavigate()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [anchor, setAnchor] = useState(todayKey())

  useEffect(() => {
    if (!open) return
    setName('')
    setDescription('')
    setAnchor(todayKey())
  }, [open])

  const submit = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    try {
      const template = await create.mutateAsync({
        name: trimmed,
        description: description.trim() || undefined,
        anchor_on: anchor || undefined,
      })
      toast.success(`Шаблон «${template.name}» создан`)
      onOpenChange(false)
      nav(`/projects/${template.id}`)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={(v) => !create.isPending && onOpenChange(v)}
      title="Новый шаблон"
      description="Соберите заготовку проекта: колонки, метки, задачи со сроками и людей. Шаблон увидят все, кто создаёт проекты."
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
            Отмена
          </Button>
          <Button onClick={() => void submit()} disabled={create.isPending || !name.trim()}>
            {create.isPending ? 'Создаём…' : 'Создать шаблон'}
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
          <Label htmlFor="new-template-name">Название</Label>
          <Input
            id="new-template-name"
            placeholder="Открытие точки"
            autoFocus
            maxLength={255}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="new-template-desc">Описание (опционально)</Label>
          <Textarea
            id="new-template-desc"
            rows={2}
            maxLength={4000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="new-template-anchor">Точка отсчёта</Label>
          <DateField id="new-template-anchor" value={anchor} onChange={setAnchor} />
          <p className="text-[13px] text-text3">
            От неё считаются сроки задач шаблона. В проекте они сдвинутся к дате старта.
          </p>
        </div>
      </form>
    </ResponsiveDialog>
  )
}
