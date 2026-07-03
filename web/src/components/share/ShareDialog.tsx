import { Check, Copy, Link as LinkIcon, Trash2 } from 'lucide-react'
import { useState } from 'react'
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
import {
  useCreateProjectShare,
  useCreateTaskShare,
  useProjectShares,
  useRevokeShare,
  useTaskShares,
} from '@/hooks/useShares'
import { cn } from '@/lib/cn'
import { type ShareResponse } from '@/lib/share'

interface ShareDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  scope: 'task' | 'project'
  entityId: string
  entityLabel: string
}

/**
 * Create/copy/revoke public links for a task or project. View-only deep-links
 * — anyone with the URL can see the same sanitized payload (no emails,
 * initials only). Revoke is mgnovenny: server filters `WHERE revoked_at IS NULL`.
 */
export function ShareDialog({
  open,
  onOpenChange,
  scope,
  entityId,
  entityLabel,
}: ShareDialogProps) {
  const projectShares = useProjectShares(
    scope === 'project' ? entityId : undefined,
    open && scope === 'project',
  )
  const taskShares = useTaskShares(
    scope === 'task' ? entityId : undefined,
    open && scope === 'task',
  )
  const createProject = useCreateProjectShare(scope === 'project' ? entityId : '')
  const createTask = useCreateTaskShare(scope === 'task' ? entityId : '')
  const revoke = useRevokeShare(scope, entityId)

  const shares =
    scope === 'project'
      ? projectShares.data
      : scope === 'task'
        ? taskShares.data
        : []
  const isLoading =
    scope === 'project' ? projectShares.isLoading : taskShares.isLoading

  const onCreate = async () => {
    try {
      const created =
        scope === 'project'
          ? await createProject.mutateAsync({})
          : await createTask.mutateAsync({})
      toast.success('Ссылка создана')
      void copyToClipboard(created.url)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Поделиться</DialogTitle>
          <DialogDescription>
            Создайте read-only ссылку на {scope === 'task' ? 'задачу' : 'проект'}
            {' '}
            «{entityLabel}». Открывается без логина. Содержит только
            инициалы (не email), без вложений-скачиваний.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {isLoading && <p className="text-sm text-text2">Загружаем ссылки…</p>}

          {shares?.length === 0 && (
            <p className="text-sm text-text3">Пока нет активных ссылок.</p>
          )}

          <ul className="space-y-1.5">
            {shares?.map((s) => (
              <ShareRow
                key={s.id}
                share={s}
                onRevoke={async () => {
                  if (!confirm('Отозвать ссылку? Доступ будет закрыт мгновенно.')) {
                    return
                  }
                  try {
                    await revoke.mutateAsync(s.token)
                    toast.success('Ссылка отозвана')
                  } catch {
                    // тост показывает глобальный onError мутаций
                  }
                }}
              />
            ))}
          </ul>

          <Button
            onClick={onCreate}
            disabled={createProject.isPending || createTask.isPending}
            className="w-full"
          >
            <LinkIcon className="h-4 w-4" />
            Создать новую ссылку
          </Button>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Закрыть
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ShareRow({
  share,
  onRevoke,
}: {
  share: ShareResponse
  onRevoke: () => Promise<void>
}) {
  const [copied, setCopied] = useState(false)

  const onCopy = async () => {
    const ok = await copyToClipboard(share.url)
    if (ok) {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } else {
      toast.error('Не удалось скопировать')
    }
  }

  return (
    <li className="flex items-center gap-2 rounded-md border border-glass-border bg-surface px-3 py-2 text-sm">
      <code className="flex-1 truncate text-xs text-text">{share.url}</code>
      <button
        type="button"
        onClick={onCopy}
        className={cn(
          'inline-flex h-8 w-8 items-center justify-center rounded text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
          copied && 'text-green',
        )}
        aria-label="Скопировать"
        title="Скопировать"
      >
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      </button>
      <button
        type="button"
        onClick={onRevoke}
        className="inline-flex h-8 w-8 items-center justify-center rounded text-text2 hover:bg-glass hover:text-red focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
        aria-label="Отозвать"
        title="Отозвать"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </li>
  )
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* fall through */
  }
  // Fallback for browsers without `navigator.clipboard` (rare; older Safari).
  try {
    const el = document.createElement('textarea')
    el.value = text
    el.setAttribute('readonly', '')
    el.style.position = 'absolute'
    el.style.left = '-9999px'
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
    return true
  } catch {
    return false
  }
}
