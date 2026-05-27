import { useEffect } from 'react'

import { authClient } from '@/lib/auth'

export function LoginRedirect() {
  useEffect(() => {
    authClient.startLogin(window.location.pathname)
  }, [])

  return (
    <div className="flex min-h-screen items-center justify-center text-text2">
      Переадресация на auth.signaris.ru…
    </div>
  )
}
