import { useId, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { useCreateFolder } from '@/hooks/useProjects'

interface CreateFolderDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
}

/**
 * Создание папки проектов. Общий для страницы «Проекты» и сайдбара —
 * на `/projects` оба экземпляра смонтированы одновременно, поэтому id поля
 * генерируется через `useId`: константный id заставил бы `<Label htmlFor>`
 * фокусировать чужое поле.
 */
export function CreateFolderDialog({ open, onOpenChange }: CreateFolderDialogProps) {
  const create = useCreateFolder()
  const [name, setName] = useState('')
  const nameId = useId()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    try {
      await create.mutateAsync(trimmed)
      toast.success('Папка создана — перетащите в неё проекты')
      setName('')
      onOpenChange(false)
    } catch {
      // тост показывает глобальный onError мутаций (в т.ч. 409 на дубль имени)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Новая папка</DialogTitle>
            <DialogDescription>
              Папки общие для компании: раскладку увидят все участники.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor={nameId}>Название</Label>
            <Input
              id={nameId}
              autoFocus
              placeholder="Маркетинг"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => onOpenChange(false)}
              disabled={create.isPending}
            >
              Отмена
            </Button>
            <Button type="submit" disabled={create.isPending || !name.trim()}>
              {create.isPending ? 'Создаём…' : 'Создать'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
