import { Send, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { MicButton, type MicState } from './MicButton'
import { AutoGrowTextarea } from '@/components/ui/AutoGrowTextarea'
import { Button } from '@/components/ui/Button'
import { useIsDesktop } from '@/hooks/useMediaQuery'

/**
 * Поле команды. Микрофона нет вовсе, пока STT не настроен на сервере:
 * неактивная кнопка выглядит как сломанная, а не как «скоро».
 *
 * Расшифровка попадает В ПОЛЕ, а не отправляется: голос не должен запускать
 * действие мимо глаз.
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
  voice,
}: {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  busy: boolean
  showHints: boolean
  voice: boolean
}) {
  const isDesktop = useIsDesktop()
  const ref = useRef<HTMLTextAreaElement>(null)
  const [mic, setMic] = useState<MicState>('idle')

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
      {mic !== 'idle' && (
        // Состояние записи — В ПОЛЕ, а не только цветом кнопки: на телефоне
        // палец закрывает кнопку, и понять, идёт ли запись, больше нечем.
        <div className="flex items-center gap-2.5 px-1">
          {mic === 'recording' && (
            <span className="flex h-3.5 items-end gap-[2px]" aria-hidden>
              {[6, 13, 9, 14, 7, 11].map((h, i) => (
                <span
                  key={i}
                  className="block w-[3px] rounded-sm bg-amber"
                  style={{ height: `${h}px` }}
                />
              ))}
            </span>
          )}
          <span className="text-[13px] leading-[1.45] text-text2">
            {mic === 'recording'
              ? 'Слушаю — отпустите, чтобы вставить текст и поправить перед отправкой'
              : 'Расшифровываю…'}
          </span>
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
        {voice && (
          <MicButton
            disabled={busy}
            onStateChange={setMic}
            onText={(text) => onChange(value ? `${value} ${text}` : text)}
          />
        )}
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
