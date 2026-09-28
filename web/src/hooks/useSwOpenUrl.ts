import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { invalidateTaskThread } from '@/hooks/useThreads'
import { decideOpenUrl, openUrlTarget, swInbox } from '@/lib/swMessages'
import { taskIdFromHref } from '@/lib/taskLinks'

/**
 * Клик по push-уведомлению: воркер присылает `OPEN_URL`, страница переходит
 * SPA-маршрутом — документ не перезагружается, а несохранённая работа в
 * других частях приложения не пропадает (раньше воркер делал
 * `client.navigate()`, то есть полную навигацию произвольной вкладки).
 *
 * Сообщение, пришедшее до монтирования Shell, ждёт в `swInbox`
 * (слушатель стоит в `main.tsx`) и доставляется здесь один раз.
 *
 * Уведомление о задаче сначала обновляет её обсуждение и ленту: без полной
 * навигации клик по пушу на УЖЕ открытой карточке ничего не перезапрашивал
 * (`decideOpenUrl` → ignore), и новый комментарий не появлялся (ОС 08.09).
 */
export function useSwOpenUrl(): void {
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()
  const current = useRef('')
  useEffect(() => {
    current.current = `${location.pathname}${location.search}${location.hash}`
  }, [location])

  useEffect(
    () =>
      swInbox.subscribe((message) => {
        const target = openUrlTarget(message.url, window.location.origin)
        const taskId = taskIdFromHref(target)
        if (taskId) void invalidateTaskThread(qc, taskId)
        const decision = decideOpenUrl({ target, current: current.current })
        if (decision.kind === 'navigate') navigate(decision.to)
      }),
    [navigate, qc],
  )
}
