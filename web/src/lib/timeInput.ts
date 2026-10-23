/**
 * Поля времени «с … до …» в сборке из записей: человек печатает `1:05`,
 * `01:05:30`, `95` (секунды) или `2м`, а сервер получает секунды. Разбор
 * прощает пробелы и точку с запятой вместо двоеточия; пустая строка — «нет».
 */

export function parseClock(raw: string): number | null {
  const text = raw.trim().replace(/[.;,]/g, ':').replace(/\s+/g, '')
  if (!text) return null
  const m = /^(\d+)(?:м|m)$/i.exec(text)
  if (m) return Number(m[1]) * 60
  if (/^\d+$/.test(text)) return Number(text)
  const parts = text.split(':')
  if (parts.length < 2 || parts.length > 3 || parts.some((p) => !/^\d+$/.test(p))) return null
  const nums = parts.map(Number)
  const [a, b, c] = nums as [number, number, number?]
  if (c === undefined) {
    if (b >= 60) return null
    return a * 60 + b
  }
  if (b >= 60 || c >= 60) return null
  return a * 3600 + b * 60 + c
}

/** Секунды → «м:сс» или «ч:мм:сс» для поля ввода (без ведущих нулей у часов/минут). */
export function formatClockInput(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return ''
  const total = Math.round(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

export interface TrimCheck {
  start: number
  end: number | null
  problem: string | null
}

/** Подрезка части против её длительности: «с» внутри записи, «до» позже «с». */
export function checkTrim(startRaw: string, endRaw: string, duration: number | null): TrimCheck {
  const start = startRaw.trim() ? parseClock(startRaw) : 0
  const end = endRaw.trim() ? parseClock(endRaw) : null
  if (start === null || (endRaw.trim() && end === null)) {
    return {
      start: start ?? 0,
      end,
      problem: 'Время — в виде м:сс или ч:мм:сс',
    }
  }
  if (duration != null && start >= duration) {
    return { start, end, problem: 'Начало подрезки за концом записи' }
  }
  if (end !== null && end <= start) {
    return { start, end, problem: '«До» раньше, чем «с»' }
  }
  if (end !== null && duration != null && end > duration + 0.5) {
    return { start, end, problem: 'Конец подрезки за концом записи' }
  }
  return { start, end, problem: null }
}

/** Длительность части после подрезки. */
export function trimmedDuration(
  duration: number | null,
  start: number,
  end: number | null,
): number | null {
  if (duration == null) return null
  const to = end === null ? duration : Math.min(end, duration)
  return Math.max(0, to - start)
}
