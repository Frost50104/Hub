import { Bell, BellOff } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
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
    } catch (err) {
      toast.error('Не получилось', { description: (err as Error).message })
    }
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={onClick}
      disabled={toggle.isPending || !myEmployeeId}
      title={iWatch ? `Отписаться (${count} следят)` : `Подписаться (${count} следят)`}
    >
      {iWatch ? (
        <Bell className="h-4 w-4 text-amber" />
      ) : (
        <BellOff className="h-4 w-4" />
      )}
      <span className="text-xs">{count}</span>
    </Button>
  )
}
