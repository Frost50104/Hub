/** Капитализация ТОЛЬКО первой буквы строки. CSS `capitalize` капитализирует
 * каждое слово — русские даты выходили «20 Июля» и «Июль 2026 Г.». */
export function capitalizeFirst(s: string): string {
  return s.length > 0 ? s[0]!.toUpperCase() + s.slice(1) : s
}
