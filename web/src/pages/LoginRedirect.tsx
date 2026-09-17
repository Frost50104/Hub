import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

import { authClient } from '@/lib/auth'

export function LoginRedirect() {
  const nav = useNavigate()

  useEffect(() => {
    // На `/login` нет смысла передавать pathname — handleCallback вернётся на
    // `/login` и снова отрендерит этот компонент → бесконечный цикл
    // login→callback→login. Lib 0.6.1+ имеет sanitizeReturnPath-страховку,
    // но дублируем тут для ясности.
    const p = window.location.pathname
    const returnPath = p === '/login' || p.startsWith('/auth/') ? '/' : p

    /**
     * С 0.12 `startLogin` из СКРЫТОЙ страницы не уходит на auth, а ждёт её
     * показа, и промис при этом резолвится сразу. Если к моменту показа вход
     * уже сделан в другой вкладке, либа отложенный переход отменяет — и эта
     * страница осталась бы с «Переадресация…» навсегда: своих запросов у неё
     * нет, поэтому рефетч из `onSessionRestored` её не двигает.
     *
     * Гонка с обработчиком показа внутри либы безопасна: если она всё-таки
     * уходит на auth, токена в сторе нет и `nav` не выполняется.
     */
    let alive = true
    const goIfSignedIn = () => {
      void authClient.getAccessToken().then((token) => {
        if (alive && token) nav(returnPath, { replace: true })
      })
    }

    void authClient.startLogin(returnPath).then(goIfSignedIn)
    document.addEventListener('visibilitychange', goIfSignedIn)
    return () => {
      alive = false
      document.removeEventListener('visibilitychange', goIfSignedIn)
    }
  }, [nav])

  return (
    <div className="flex min-h-screen items-center justify-center text-text2">
      Переадресация на auth.signaris.ru…
    </div>
  )
}
