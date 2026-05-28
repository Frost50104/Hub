import { Bell, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { usePush } from '@/hooks/usePush'

const DISMISS_KEY = 'hub:push-prompt-dismissed'

export function PushPermissionPrompt() {
  const { permission, subscribed, subscribe } = usePush()
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem(DISMISS_KEY) === '1',
  )

  // Only show on `default` (user hasn't decided yet) and only if not already subscribed.
  if (
    permission !== 'default' ||
    subscribed ||
    dismissed
  ) {
    return null
  }

  return (
    <div className="glass mx-auto flex max-w-3xl items-center gap-4 p-4 shadow-glass">
      <Bell className="h-6 w-6 shrink-0 text-amber" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-text">
          Включить уведомления о задачах?
        </p>
        <p className="text-xs text-text2">
          Push о назначениях, @упоминаниях и комментариях в задачах, за которыми вы следите.
        </p>
      </div>
      <Button
        size="sm"
        onClick={async () => {
          try {
            const ok = await subscribe()
            if (ok) {
              toast.success('Уведомления включены')
            } else {
              toast.message('Браузер не дал разрешение', {
                description: 'Можно включить позже в Settings → Privacy → Notifications',
              })
            }
          } catch (err) {
            toast.error('Не удалось подписаться', {
              description: (err as Error).message,
            })
          }
        }}
      >
        Включить
      </Button>
      <button
        onClick={() => {
          sessionStorage.setItem(DISMISS_KEY, '1')
          setDismissed(true)
        }}
        className="rounded p-1 text-text3 hover:bg-glass hover:text-text"
        aria-label="Закрыть"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}
