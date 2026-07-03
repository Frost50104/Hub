import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import {
  useCreateLabel,
  useDeleteLabel,
  useLabels,
  useUpdateLabel,
} from '@/hooks/useLabels'
import { type Label } from '@/lib/labels'

interface LabelsManagerProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Управление метками проекта (owner-only — кнопка входа видна только owner'у). */
export function LabelsManager({ projectId, open, onOpenChange }: LabelsManagerProps) {
  const labels = useLabels(open ? projectId : undefined)
  const create = useCreateLabel(projectId)
  const [name, setName] = useState('')
  const [color, setColor] = useState('#FFB200')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    try {
      await create.mutateAsync({ name: trimmed, color })
      toast.success(`Метка «${trimmed}» создана`)
      setName('')
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Метки проекта</DialogTitle>
          <DialogDescription>
            Теги для задач: имя + цвет. Вешаются на задачу в её карточке,
            фильтр — в панели фильтров.
          </DialogDescription>
        </DialogHeader>

        <section className="space-y-1">
          {labels.isLoading && <p className="text-sm text-text2">Загружаем…</p>}
          {labels.data?.length === 0 && (
            <p className="text-sm text-text3">Пока нет меток.</p>
          )}
          {labels.data?.map((l) => (
            <LabelRow key={l.id} label={l} projectId={projectId} />
          ))}
        </section>

        <form onSubmit={submit} className="flex items-center gap-2 pt-2">
          <input
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            aria-label="Цвет новой метки"
            className="h-8 w-8 shrink-0 cursor-pointer rounded border border-glass-border bg-glass"
          />
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Новая метка"
            className="h-8"
          />
          <Button type="submit" size="sm" disabled={!name.trim() || create.isPending}>
            <Plus className="h-4 w-4" /> Создать
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function LabelRow({ label, projectId }: { label: Label; projectId: string }) {
  const update = useUpdateLabel(projectId)
  const remove = useDeleteLabel(projectId)
  const [draft, setDraft] = useState(label.name)

  const commitName = () => {
    const trimmed = draft.trim()
    if (!trimmed || trimmed === label.name) {
      setDraft(label.name)
      return
    }
    update.mutate({ labelId: label.id, body: { name: trimmed } })
  }

  return (
    <div className="flex items-center gap-2 rounded-md border border-glass-border px-2 py-1.5">
      <input
        type="color"
        value={label.color}
        onChange={(e) =>
          update.mutate({ labelId: label.id, body: { color: e.target.value } })
        }
        aria-label={`Цвет метки ${label.name}`}
        className="h-6 w-6 shrink-0 cursor-pointer rounded border border-glass-border bg-glass"
      />
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commitName}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            ;(e.target as HTMLInputElement).blur()
          } else if (e.key === 'Escape') {
            setDraft(label.name)
          }
        }}
        className="h-7 border-transparent bg-transparent"
      />
      <Button
        variant="ghost"
        size="icon"
        aria-label={`Удалить метку ${label.name}`}
        onClick={async () => {
          if (!confirm(`Удалить метку «${label.name}»? Она снимется со всех задач.`)) {
            return
          }
          try {
            await remove.mutateAsync(label.id)
            toast.success(`Метка «${label.name}» удалена`)
          } catch {
            // тост показывает глобальный onError мутаций
          }
        }}
      >
        <Trash2 className="h-4 w-4 text-red" />
      </Button>
    </div>
  )
}
