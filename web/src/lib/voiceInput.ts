/**
 * Голосовой ввод ассистента: правила без React и без сети (vitest без jsdom).
 *
 * Предел длины записи задаёт сервер — `/ai/status.voice_max_sec` из
 * `stt_max_audio_sec`. Длиннее сервис распознавания отвечает 413, и диктовка
 * пропала бы целиком, поэтому микрофон останавливает запись сам, с запасом:
 * длина звука считается на сервере после декодирования.
 */

/** Запас до серверного предела. */
export const VOICE_STOP_MARGIN_SEC = 5

/** Через сколько миллисекунд остановить запись; null — предела нет. */
export function voiceAutoStopMs(maxSec: number | null | undefined): number | null {
  if (typeof maxSec !== 'number' || !Number.isFinite(maxSec) || maxSec <= 0) return null
  return Math.max(1, maxSec - VOICE_STOP_MARGIN_SEC) * 1000
}

const VOICE_ERROR_FALLBACK = 'Не удалось распознать запись — наберите команду текстом'

/**
 * Текст тоста при сбое расшифровки. Причину сервер формулирует сам («запись
 * длиннее 60 с», «распознавание запускается»): 503 значит не только «не
 * подключено», но и «перезапускается», поэтому своего текста по коду ответа
 * нет. Обрыв сети приходит без `detail` — английское «Network Error» людям
 * не показываем.
 */
export function voiceErrorText(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } } | null)?.response?.data
    ?.detail
  return typeof detail === 'string' && detail.trim() ? detail : VOICE_ERROR_FALLBACK
}
