import { useState } from 'react'

import { Button } from '@/components/ui/Button'

/**
 * Последний экран, когда ошибка рендера прошла все границы.
 *
 * ПОКАЗЫВАЕТ текст ошибки, и это не «отладочная роскошь». 27.08 сотрудник
 * прислал скриншот этого экрана с телефона — и выяснить причину было нечем:
 * Sentry DSN в Hub не настроен (`docs/tech-debt/open.md`), консоль на iOS без
 * Mac не открыть, а прежний текст обещал «мы уже знаем об ошибке», хотя не
 * знал никто. Пока Sentry выключен, единственный канал диагностики — человек,
 * который может переслать текст.
 */
export function ErrorFallback({ error }: { error?: unknown }) {
  const [copied, setCopied] = useState(false)
  const detail = describeError(error, window.location.pathname + window.location.search)

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="glass max-w-md space-y-3 p-6 text-center">
        <h1 className="font-display text-lg font-semibold text-text">
          Что-то пошло не так
        </h1>
        <p className="text-sm text-text2">
          Попробуйте обновить страницу — большинство сбоев лечится этим. Если
          повторится, пришлите текст ниже: без него причину не найти.
        </p>
        {detail && (
          <p className="max-h-40 overflow-auto rounded-lg border border-glass-border bg-glass p-2.5 text-left font-mono text-[11px] leading-[1.45] text-text2">
            {detail}
          </p>
        )}
        <div className="flex flex-wrap justify-center gap-2">
          <Button onClick={() => window.location.reload()}>Обновить страницу</Button>
          {detail && (
            <Button
              variant="secondary"
              onClick={() => {
                void navigator.clipboard
                  ?.writeText(detail)
                  .then(() => setCopied(true))
                  .catch(() => setCopied(false))
              }}
            >
              {copied ? 'Скопировано' : 'Скопировать ошибку'}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Текст ошибки для человека: сообщение, первая строка стека и адрес.
 *
 * Адрес нужен обязательно — «упало на каком-то экране» не диагноз, а стек
 * в проде минифицирован и без первой строки бесполезен. Приходит ПАРАМЕТРОМ,
 * а не читается из `window`: иначе функцию нельзя было бы проверить — vitest
 * в этом проекте бежит без jsdom.
 */
export function describeError(error: unknown, path: string): string | null {
  const parts: string[] = []
  if (error instanceof Error) {
    parts.push(`${error.name}: ${error.message}`)
    const frame = error.stack?.split('\n')[1]?.trim()
    if (frame) parts.push(frame)
  } else if (typeof error === 'string') {
    parts.push(error)
  } else if (error) {
    try {
      parts.push(JSON.stringify(error).slice(0, 300))
    } catch {
      parts.push(String(error))
    }
  }
  if (!parts.length) return null
  parts.push(path)
  return parts.join('\n')
}
