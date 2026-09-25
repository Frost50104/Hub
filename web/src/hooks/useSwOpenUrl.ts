import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { decideOpenUrl, openUrlTarget, swInbox } from '@/lib/swMessages'

/**
 * Клик по push-уведомлению: воркер присылает `OPEN_URL`, страница переходит
 * SPA-маршрутом — документ не перезагружается, а несохранённая работа в
 * других частях приложения не пропадает (раньше воркер делал
 * `client.navigate()`, то есть полную навигацию произвольной вкладки).
 *
 * Сообщение, пришедшее до монтирования Shell, ждёт в `swInbox`
 * (слушатель стоит в `main.tsx`) и доставляется здесь один раз.
 */
export function useSwOpenUrl(): void {
  const navigate = useNavigate()
  const location = useLocation()
  const current = useRef('')
  useEffect(() => {
    current.current = `${location.pathname}${location.search}${location.hash}`
  }, [location])

  useEffect(
    () =>
      swInbox.subscribe((message) => {
        const decision = decideOpenUrl({
          target: openUrlTarget(message.url, window.location.origin),
          current: current.current,
        })
        if (decision.kind === 'navigate') navigate(decision.to)
      }),
    [navigate],
  )
}
