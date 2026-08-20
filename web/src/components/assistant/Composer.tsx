import { Send, Sparkles } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { AutoGrowTextarea } from '@/components/ui/AutoGrowTextarea'
import { Button } from '@/components/ui/Button'
import { useIsDesktop } from '@/hooks/useMediaQuery'

/**
 * Поле команды. Микрофон появится волной 3 — до тех пор кнопки нет вовсе:
 * неактивная кнопка микрофона выглядит как сломанная, а не как «скоро».
 * (Плюс `Permissions-Policy: microphone=()` на nginx всё равно глушит запись
 * до правки конфига — см. план.)
 */
const HINTS = [
  'Что просрочено у меня',
  'Сводка по проекту',
  'Кто перегружен на этой неделе',
]

export function Composer({
  value,
  onChange,
  onSubmit,
  busy,
  showHints,
}: {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  busy: boolean
  showHints: boolean
}) {
  const isDesktop = useIsDesktop()
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (isDesktop) ref.current?.focus()
  }, [isDesktop])

  const canSend = value.trim().length >= 3 && !busy

  return (
    <div className="space-y-2.5">
      {showHints && (
        <div className="flex flex-wrap gap-2">
          {HINTS.map((hint) => (
            <button
              key={hint}
              type="button"
              onClick={() => onChange(hint)}
              className="inline-flex min-h-[34px] items-center rounded-full border border-glass-border px-3 text-[13px] font-medium text-text2 hover:border-amber/40 hover:text-text"
            >
              {hint}
            </button>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2.5 rounded-2xl border border-glass-border bg-surface p-3 pl-4">
        {/* Обёртка держит ширину: сам AutoGrowTextarea — это grid-двойник,
            и flex-1 на textarea внутри него не сработал бы. */}
        <div className="min-w-0 flex-1">
          <AutoGrowTextarea
            ref={ref}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && isDesktop) {
                e.preventDefault()
                if (canSend) onSubmit()
              }
            }}
            placeholder="Команда или вопрос — например «что просрочено у Дмитрия»"
            className="border-0 bg-transparent p-0 text-[16px] leading-[1.45] text-text placeholder:text-text2 focus-visible:outline-none focus-visible:ring-0"
          />
        </div>
        <Button
          size={isDesktop ? 'lg' : 'icon'}
          className="h-11 shrink-0 rounded-[11px]"
          disabled={!canSend}
          onClick={onSubmit}
          aria-label="Отправить"
        >
          {isDesktop ? (
            <>
              <Sparkles className="h-4 w-4" />
              Выполнить
            </>
          ) : (
            <Send className="h-4 w-4" />
          )}
        </Button>
      </div>
    </div>
  )
}
