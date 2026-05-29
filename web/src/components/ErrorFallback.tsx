import { Button } from '@/components/ui/Button'

/**
 * Last-resort UI when a render error escapes every boundary inside the app.
 * Wrapped by Sentry.ErrorBoundary in App.tsx — the SDK already captured the
 * exception by the time this renders.
 */
export function ErrorFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="glass max-w-md space-y-3 p-6 text-center">
        <h1 className="font-display text-lg font-semibold text-text">
          Что-то пошло не так
        </h1>
        <p className="text-sm text-text2">
          Мы уже знаем об ошибке. Попробуйте обновить страницу — большинство
          сбоев лечится этим.
        </p>
        <Button onClick={() => window.location.reload()}>Обновить страницу</Button>
      </div>
    </div>
  )
}
