import { Bell, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { usePush } from '@/hooks/usePush'
import { cn } from '@/lib/cn'
import {
  PUSH_NUDGE_DISMISS_KEY,
  PUSH_NUDGE_DISMISS_MS,
  isIosUa,
  pushNudgeKind,
  pushNudgeText,
  readDismissedUntil,
} from '@/lib/pushNudge'
import { isStandalone } from '@/lib/standalone'

function readDismissed(): number | null {
  try {
    return readDismissedUntil(localStorage.getItem(PUSH_NUDGE_DISMISS_KEY))
  } catch {
    return null
  }
}

/**
 * Карточка «включите уведомления». Ветки — `lib/pushNudge.ts`: iPhone во
 * вкладке Safari получает инструкцию про экран «Домой» (там push вообще
 * `unsupported`), остальным — кнопка. `race` — текст про гонку для сотрудников
 * точек-участниц; живёт на главных обоих пространств и на странице гонки.
 */
export function PushPermissionPrompt({ race = false, className }: { race?: boolean; className?: string }) {
  const { permission, subscribed, checked, subscribe } = usePush()
  const [dismissedUntil, setDismissedUntil] = useState<number | null>(readDismissed)
  const kind = pushNudgeKind({
    permission,
    subscribed,
    checked,
    ios: isIosUa(navigator.userAgent, navigator.maxTouchPoints ?? 0),
    standalone: isStandalone(),
    dismissedUntil,
    now: Date.now(),
  })
  if (!kind) return null
  const text = pushNudgeText(kind, race)

  const dismiss = () => {
    const until = Date.now() + PUSH_NUDGE_DISMISS_MS
    try {
      localStorage.setItem(PUSH_NUDGE_DISMISS_KEY, String(until))
    } catch {
      // приватное окно — спрячем до перезагрузки
    }
    setDismissedUntil(until)
  }

  const enable = async () => {
    try {
      const ok = await subscribe()
      if (ok) toast.success('Уведомления включены')
      else
        toast.message('Браузер не дал разрешение', {
          description: 'Можно включить позже в Настройках → Уведомления',
        })
    } catch (err) {
      toast.error('Не удалось подписаться', { description: (err as Error).message })
    }
  }

  return (
    <div className={cn('glass mx-auto flex max-w-3xl items-center gap-4 p-4 shadow-glass', className)} role="status">
      <Bell className="h-6 w-6 shrink-0 text-amber" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-text">{text.title}</p>
        <p className="text-xs text-text2">{text.body}</p>
      </div>
      {text.action &&
        (kind === 'denied' ? (
          <Link to="/settings/notifications" className="shrink-0 rounded-lg border border-hair px-3 py-1.5 text-[13px] font-semibold text-text hover:bg-glass">
            {text.action}
          </Link>
        ) : (
          <Button size="sm" onClick={() => void enable()}>
            {text.action}
          </Button>
        ))}
      <button type="button" onClick={dismiss} className="rounded p-1 text-text3 hover:bg-glass hover:text-text" aria-label="Позже">
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}
