import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { type AppUpdateStatus, runUpdateClick } from '@/lib/appUpdate'
import { updateClickDeps } from '@/lib/swBrowser'
import { hungBrowserHint, isDesktopMacUa } from '@/lib/swPolicy'

export type { AppUpdateStatus }

/**
 * Ручное обновление приложения: баннер «Доступно обновление» и «Обновить
 * приложение» в Настройках зовут один и тот же путь — `lib/appUpdate.ts`.
 *
 * Здесь только React-состояние кнопки и тосты; ни одного обращения к
 * воркеру. Что и почему — в шапке `lib/appUpdate.ts` и `lib/swPolicy.ts`
 * (разбор 25.09: 30 с на клик в Safari с зависшей регистрацией).
 */
export function useAppUpdate(): {
  status: AppUpdateStatus
  checkForUpdate: () => void
} {
  const [status, setStatus] = useState<AppUpdateStatus>('idle')
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const checkForUpdate = useCallback(() => {
    // Повторный клик не запускает вторую проверку.
    if (status !== 'idle') return
    const deps = updateClickDeps((next) => {
      if (alive.current) setStatus(next)
    })
    runUpdateClick(deps)
      .then((outcome) => {
        if (!alive.current || outcome.action.kind !== 'toast') return
        switch (outcome.action.reason) {
          case 'offline':
            toast.error('Нет соединения', { description: 'Проверьте соединение и попробуйте ещё раз.' })
            return
          case 'unreachable':
            toast.error('Не удалось проверить обновления', {
              description: 'Попробуйте ещё раз или перезагрузите страницу.',
            })
            return
          case 'latest':
            toast.success('У вас последняя версия')
            return
          case 'latest-hung':
            toast.success('У вас последняя версия', {
              description: hungBrowserHint(isDesktopMacUa(navigator.userAgent, navigator.maxTouchPoints)),
              duration: 12_000,
            })
        }
      })
      .catch(() => {
        if (!alive.current) return
        setStatus('idle')
        toast.error('Не удалось проверить обновления', {
          description: 'Попробуйте ещё раз или перезагрузите страницу.',
        })
      })
  }, [status])

  return { status, checkForUpdate }
}
