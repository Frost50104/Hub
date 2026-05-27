import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { authClient } from '@/lib/auth'

export function AuthCallback() {
  const nav = useNavigate()
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    authClient
      .handleCallback(window.location.search)
      .then(({ returnPath }) => nav(returnPath ?? '/', { replace: true }))
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
