import { Bell, BellOff } from 'lucide-react'
import { toast } from 'sonner'

import { cn } from '@/lib/cn'
import { useMe } from '@/hooks/useMe'
import { useToggleWatch, useWatchers } from '@/hooks/useThreads'

interface WatchControlProps {
  taskId: string
}

export function WatchControl({ taskId }: WatchControlProps) {
  const me = useMe()
  const watchers = useWatchers(taskId)
  const toggle = useToggleWatch(taskId)

  const myEmployeeId = me.data?.employee_id
  const iWatch = !!myEmployeeId && (watchers.data ?? []).some(
    (w) => w.employee_id === myEmployeeId,
  )
  const count = watchers.data?.length ?? 0

  const onClick = async () => {
    try {
      await toggle.mutateAsync(iWatch)
      toast.success(iWatch ? 'Вы отписались от задачи' : 'Вы подписались на задачу')
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={toggle.isPending || !myEmployeeId}
      title={iWatch ? `Отписаться (${count} следят)` : `Подписаться (${count} следят)`}
      aria-label={iWatch ? 'Отписаться от задачи' : 'Подписаться на задачу'}
      className={cn(
        'flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-[13px] font-semibold hover:bg-glass lg:min-h-8',
        iWatch ? 'text-amber' : 'text-text2 hover:text-text',
      )}
    >
      {iWatch ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
      {count > 0 && <span className="font-mono">{count}</span>}
    </button>
  )
}
