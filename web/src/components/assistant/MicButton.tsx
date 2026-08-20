import { Mic } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { cn } from '@/lib/cn'
import { assistantApi } from '@/lib/assistant'

/**
 * Микрофон 44×44, радиус 11 — удержание записывает, отпускание расшифровывает.
 *
 * Расшифровка попадает В ПОЛЕ ВВОДА, а не отправляется командой: голос не
 * должен запускать действие мимо глаз (спека макета). Отправка остаётся
 * отдельной кнопкой.
 *
 * Ошибки не глушим. Отказ в доступе к микрофону и «распознавание недоступно» —
 * разные ситуации с разными действиями пользователя, и молчащая кнопка хуже
 * обеих.
 */
type State = 'idle' | 'recording' | 'working'

function pickMimeType(): string | undefined {
  // Chrome/Android отдают webm/opus, Safari — mp4/aac. Оба формата сервер
  // декодирует напрямую из байтов; список — по убыванию предпочтения.
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
  return candidates.find((t) => MediaRecorder.isTypeSupported(t))
}

export function MicButton({
  onText,
  disabled,
}: {
  onText: (text: string) => void
  disabled?: boolean
}) {
  const [state, setState] = useState<State>('idle')
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)

  // Микрофон нужно отпускать: иначе в Chrome остаётся красная точка записи,
  // а на телефоне — включённый датчик.
  const stopStream = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
  }
  useEffect(() => stopStream, [])

  const start = async () => {
    if (state !== 'idle' || disabled) return
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      toast.error('Браузер не умеет записывать звук — наберите команду текстом')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mimeType = pickMimeType()
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      chunksRef.current = []
      rec.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data)
      }
      rec.onstop = () => {
        stopStream()
        const blob = new Blob(chunksRef.current, { type: rec.mimeType })
        if (blob.size < 1200) {
          // Меньше килобайта — это случайное касание, а не команда.
          setState('idle')
          return
        }
        setState('working')
        assistantApi
          .transcribe(blob)
          .then((text) => {
            if (text.trim()) onText(text.trim())
            else toast.error('Ничего не расслышал — попробуйте ещё раз')
          })
          .catch((e: unknown) => {
            const status = (e as { response?: { status?: number } })?.response?.status
            toast.error(
              status === 503
                ? 'Распознавание речи не подключено — наберите команду текстом'
                : 'Не удалось распознать запись',
            )
          })
          .finally(() => setState('idle'))
      }
      recorderRef.current = rec
      rec.start()
      setState('recording')
    } catch {
      stopStream()
      // NotAllowedError приходит и при отказе пользователя, и когда микрофон
      // заглушён Permissions-Policy — текст должен вести к обоим решениям.
      toast.error('Микрофон недоступен', {
        description: 'Разрешите доступ в браузере или наберите команду текстом',
      })
      setState('idle')
    }
  }

  const stop = () => {
    if (state !== 'recording') return
    recorderRef.current?.stop()
    recorderRef.current = null
  }

  const recording = state === 'recording'
  return (
    <button
      type="button"
      aria-label={recording ? 'Отпустите, чтобы расшифровать' : 'Записать голосом'}
      aria-pressed={recording}
      disabled={disabled || state === 'working'}
      onPointerDown={(e) => {
        e.preventDefault()
        void start()
      }}
      onPointerUp={stop}
      onPointerLeave={stop}
      onPointerCancel={stop}
      className={cn(
        'flex h-11 w-11 shrink-0 items-center justify-center rounded-[11px] border transition-colors',
        recording
          ? 'border-transparent bg-amber text-on-amber'
          : 'border-glass-border text-text2 hover:text-text',
        state === 'working' && 'opacity-60',
      )}
    >
      <Mic className={cn('h-[18px] w-[18px]', state === 'working' && 'animate-pulse')} />
    </button>
  )
}
