import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { meQueryOptions } from '@/hooks/useMe'
import { authClient } from '@/lib/auth'
import { queryClient } from '@/lib/queryClient'

export function AuthCallback() {
  const nav = useNavigate()
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    authClient
      .handleCallback(window.location.search)
      // /me ДО перехода в приложение: тема принадлежит аккаунту, и без этого
      // первый экран после входа на чужом устройстве мигал бы прошлой темой.
      // Ждём максимум секунду и не мешаем входу, если /me молчит или падает.
      .then(async ({ returnPath }) => {
        await Promise.race([
          queryClient.fetchQuery(meQueryOptions).catch(() => undefined),
          new Promise((r) => setTimeout(r, 1000)),
        ])
        nav(returnPath ?? '/', { replace: true })
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
  }, [nav])

  if (err) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-4 text-text2">
        <h2 className="text-red text-xl font-display">Ошибка авторизации</h2>
        <p className="max-w-md text-center text-sm">{err}</p>
        <a className="text-amber underline" href="/login">
          Попробовать ещё раз
        </a>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center text-text2">
      Подтверждаем вход…
    </div>
  )
}
