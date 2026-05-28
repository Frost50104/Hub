import { useEffect } from 'react'

import { authClient } from '@/lib/auth'

export function LoginRedirect() {
  useEffect(() => {
    // На `/login` нет смысла передавать pathname — handleCallback вернётся на
    // `/login` и снова отрендерит этот компонент → бесконечный цикл
    // login→callback→login. Lib 0.6.1+ имеет sanitizeReturnPath-страховку,
    // но дублируем тут для ясности.
    const p = window.location.pathname
    const returnPath = p === '/login' || p.startsWith('/auth/') ? '/' : p
    authClient.startLogin(returnPath)
  }, [])

  return (
    <div className="flex min-h-screen items-center justify-center text-text2">
      Переадресация на auth.signaris.ru…
    </div>
  )
}
