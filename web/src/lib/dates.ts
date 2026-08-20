/** Капитализация ТОЛЬКО первой буквы строки. CSS `capitalize` капитализирует
 * каждое слово — русские даты выходили «20 Июля» и «Июль 2026 Г.». */
export function capitalizeFirst(s: string): string {
  return s.length > 0 ? s[0]!.toUpperCase() + s.slice(1) : s
}

/**
 * «Последние данные — 3 минуты назад» для состояний ошибки: человек должен
 * понимать, насколько стары данные, которые он всё ещё видит. `null`, если
 * данных не было вовсе (TanStack `dataUpdatedAt === 0`).
 */
export function dataAgeLabel(updatedAt: number, now: number = Date.now()): string | null {
  if (!updatedAt) return null
  const min = Math.max(0, Math.round((now - updatedAt) / 60000))
  if (min < 1) return 'Последние данные — только что'
  if (min < 60) {
    const w = min % 10 === 1 && min % 100 !== 11 ? 'минуту' : min % 10 >= 2 && min % 10 <= 4 && (min % 100 < 12 || min % 100 > 14) ? 'минуты' : 'минут'
    return `Последние данные — ${min} ${w} назад`
  }
  const h = Math.round(min / 60)
  const w = h % 10 === 1 && h % 100 !== 11 ? 'час' : h % 10 >= 2 && h % 10 <= 4 && (h % 100 < 12 || h % 100 > 14) ? 'часа' : 'часов'
  return `Последние данные — ${h} ${w} назад`
}
