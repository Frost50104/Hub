/**
 * Чип метки: цвет — её единственный смысл, поэтому заливка плотная, а краска
 * ВЫЧИСЛЯЕТСЯ, а не назначается.
 *
 * Цвет приходит из labels API и может быть любой светлоты (бирюзовый #00B4A8 с
 * тёмной краской давал 2,47:1). Берём ту из двух красок, что контрастнее, и
 * если даже она не даёт 4,5:1 — притемняем саму заливку шагом 0,86, но не
 * больше пяти раз: дальше светлые метки разных тонов сходятся в один тёмный и
 * перестают различаться, а различать их — единственная задача цвета.
 *
 * Краски фиксированные (#08080E / #F0F0F5) и НЕ флипаются с темой: заливка
 * чипа — собственный цвет метки, одинаковый в обеих темах.
 */

const DARK = '#08080E'
const LIGHT = '#F0F0F5'
const TARGET = 4.5
const STEP = 0.86
const MAX_STEPS = 5
/** Цвет метки вводит администратор, в БД он не валидируется. */
const FALLBACK = '#9090A8'

export interface ChipColors {
  background: string
  color: string
}

/** #abc | #aabbcc | rgb(1,2,3) → [r,g,b]; мусор → null. */
function parseColor(input: string): [number, number, number] | null {
  const raw = input.trim()
  const hex = raw.replace(/^#/, '')
  if (/^[0-9a-f]{3}$/i.test(hex)) {
    const [r, g, b] = [...hex].map((c) => parseInt(c + c, 16))
    return [r!, g!, b!]
  }
  if (/^[0-9a-f]{6}$/i.test(hex)) {
    const n = parseInt(hex, 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  const m = /^rgba?\(([^)]+)\)$/i.exec(raw)
  if (m) {
    const parts = m[1]!.split(/[\s,/]+/).filter(Boolean).slice(0, 3).map(Number)
    if (parts.length === 3 && parts.every((v) => Number.isFinite(v))) {
      return parts.map((v) => Math.min(255, Math.max(0, Math.round(v)))) as [
        number,
        number,
        number,
      ]
    }
  }
  return null
}

function toHex([r, g, b]: [number, number, number]): string {
  return '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')
}

/** Относительная яркость по WCAG 2.1. */
export function luminance(rgb: [number, number, number]): number {
  const [r, g, b] = rgb.map((v) => {
    const s = v / 255
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  }) as [number, number, number]
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrast(a: number, b: number): number {
  const [hi, lo] = a > b ? [a, b] : [b, a]
  return (hi + 0.05) / (lo + 0.05)
}

function darken(rgb: [number, number, number], k: number): [number, number, number] {
  return rgb.map((v) => Math.round(v * k)) as [number, number, number]
}

/**
 * Заливка и краска чипа для произвольного пользовательского цвета.
 * Гарантия: возвращённая пара даёт ≥4,5:1, если это достижимо за пять шагов
 * затемнения (для реальных цветов метки достижимо всегда).
 */
export function labelChipColors(input: string | null | undefined): ChipColors {
  let fill = parseColor(input || '') ?? parseColor(FALLBACK)!
  const darkLum = luminance(parseColor(DARK)!)
  const lightLum = luminance(parseColor(LIGHT)!)

  for (let i = 0; i < MAX_STEPS; i++) {
    const l = luminance(fill)
    if (Math.max(contrast(l, darkLum), contrast(l, lightLum)) >= TARGET) break
    fill = darken(fill, STEP)
  }
  const l = luminance(fill)
  return {
    background: toHex(fill),
    color: contrast(l, darkLum) >= contrast(l, lightLum) ? DARK : LIGHT,
  }
}
