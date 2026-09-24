import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { useUnreadCount } from '@/hooks/useNotifications'
import { notificationsApi } from '@/lib/notifications'
import { shouldToastReminder } from '@/lib/taskReminders'

/**
 * Тост «Напоминание» в открытом приложении (0062).
 *
 * Пуш-подписка есть у меньшинства сотрудников (замер 18.09: 3 из 137 людей
 * точек), и без тоста напоминание у остальных было бы тихим бейджем
 * «Входящих». Счётчик непрочитанных и так опрашивается раз в 60 с — когда он
 * вырос, смотрим новейшее непрочитанное, и если это свежее напоминание,
 * показываем его. Правило — чистая `shouldToastReminder`.
 */
export function useReminderToasts(enabled: boolean): void {
  const unread = useUnreadCount()
  const navigate = useNavigate()
  const prev = useRef<number | undefined>(undefined)
  const shownId = useRef<number | null>(null)
  const next = unread.data?.count

  useEffect(() => {
    if (next === undefined) return
    const before = prev.current
    prev.current = next
    if (!enabled || before === undefined || next <= before) return
    let cancelled = false
    notificationsApi
      .list({ unread_only: true, limit: 1 })
      .then(([latest]) => {
        if (cancelled || !latest || latest.id === shownId.current) return
        if (!shouldToastReminder(before, next, latest, Date.now())) return
        shownId.current = latest.id
        const url = latest.url
        toast(latest.title, {
          description: latest.body,
          duration: 10_000,
          action: url ? { label: 'Открыть', onClick: () => navigate(url) } : undefined,
        })
      })
      .catch(() => {
        // Тост — удобство: сбой запроса не должен всплывать ошибкой.
      })
    return () => {
      cancelled = true
    }
  }, [next, enabled, navigate])
}
