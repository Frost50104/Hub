/** Обратный отсчёт до конца/старта заезда — чистые функции под vitest. */
import { plural } from '@/lib/typography'

export interface CountdownParts {
  over: boolean
  days: number
  hours: number
  minutes: number
  seconds: number
  totalMs: number
}

export function countdownParts(targetIso: string, now: number): CountdownParts {
  const totalMs = new Date(targetIso).getTime() - now
  if (!Number.isFinite(totalMs) || totalMs <= 0) {
    return { over: true, days: 0, hours: 0, minutes: 0, seconds: 0, totalMs: Math.min(0, totalMs || 0) }
  }
  const total = Math.floor(totalMs / 1000)
  return {
    over: false,
    days: Math.floor(total / 86400),
    hours: Math.floor((total % 86400) / 3600),
    minutes: Math.floor((total % 3600) / 60),
    seconds: total % 60,
    totalMs,
  }
}

function two(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

export function clockPart(p: CountdownParts): string {
  return `${two(p.hours)}:${two(p.minutes)}:${two(p.seconds)}`
}

export type CountdownMode = 'to-end' | 'to-start'

/**
 * «Осталось 1 день 02:03:04», «Осталось 02:03:04», «Старт через …»,
 * «Заезд завершён». `compact` — без слова-префикса (ТВ-панель).
 */
export function formatCountdown(p: CountdownParts, mode: CountdownMode, compact = false): string {
  if (p.over) return mode === 'to-end' ? 'Заезд завершён' : 'Заезд стартует'
  const clock = p.days > 0 ? `${plural(p.days, 'день', 'дня', 'дней')} ${clockPart(p)}` : clockPart(p)
  if (compact) return clock
  return mode === 'to-end' ? `Осталось ${clock}` : `Старт через ${clock}`
}

/** Сколько ждать до следующей целой секунды — тик без дрейфа. */
export function nextTickMs(now: number): number {
  const rest = 1000 - (now % 1000)
  return rest === 0 ? 1000 : rest
}
