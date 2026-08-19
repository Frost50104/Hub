import { DrawerSection } from '@/components/task/DrawerSection'
import { AvatarStack } from '@/components/ui/AvatarStack'
import { useWatchers } from '@/hooks/useThreads'
import { plural } from '@/lib/typography'

/**
 * «Наблюдатели» внизу карточки: кто получит уведомления по этой задаче.
 * Подписка/отписка живёт в шапке (WatchControl) — здесь только состав,
 * иначе одно действие имело бы две кнопки.
 */
export function TaskWatchers({ taskId }: { taskId: string }) {
  const watchers = useWatchers(taskId)
  const list = watchers.data ?? []
  if (list.length === 0) return null

  return (
    <DrawerSection title="Наблюдатели" count={list.length} className="border-t border-hair pt-4">
      <div className="flex items-center gap-2">
        <AvatarStack
          people={list.map((w) => ({
            employee_id: w.employee_id,
            email: w.email,
            full_name: w.full_name,
          }))}
          max={4}
        />
        <span className="text-[13px] text-text2">
          {plural(list.length, 'человек следит', 'человека следят', 'человек следят')}
        </span>
      </div>
    </DrawerSection>
  )
}
