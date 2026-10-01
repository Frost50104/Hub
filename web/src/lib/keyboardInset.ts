/**
 * Экранная клавиатура и мобильные шторки.
 *
 * iOS при показе клавиатуры НЕ уменьшает layout viewport (к нему привязаны
 * `position: fixed` и `vh`), уменьшается только `window.visualViewport`.
 * Шторка `fixed; bottom: 0` поэтому остаётся под клавиатурой, и поле поиска
 * в ней видно ровно до тех пор, пока шторка достаточно высокая (ОС 01.10:
 * «Исполнители» — после ввода выдача короткая, шторка сжалась, поле уехало
 * под клавиатуру). Android Chrome с 108 ведёт себя так же
 * (`interactive-widget=resizes-visual` по умолчанию) — один код-путь.
 *
 * Чистая арифметика здесь, подписка на события — `hooks/useKeyboardInset.ts`.
 */

export interface ViewportSnapshot {
  /** `window.innerHeight` — высота layout viewport. */
  innerHeight: number
  /** `visualViewport.height`. */
  vvHeight: number
  /** `visualViewport.offsetTop` — iOS панорамирует visual viewport к полю. */
  vvOffsetTop: number
  /** `visualViewport.scale` — пинч-зум; `user-scalable=no` iOS игнорирует. */
  scale: number
}

export interface KeyboardInset {
  /** Расстояние от низа layout viewport до низа visual viewport, px —
   *  верх клавиатуры в координатах `position: fixed; bottom`. */
  inset: number
  /** Высота видимой области, px — потолок высоты шторки. */
  viewportHeight: number
}

const SCALE_TOLERANCE = 0.01

/**
 * Мёртвой зоны нет намеренно: полоса-аксессуар внешней клавиатуры iPhone —
 * ≈44pt, и её прятать нельзя. При зуме (`scale ≠ 1`, iOS отдаёт 1.0000001)
 * visual viewport меньше по другой причине — считаем «клавиатуры нет».
 */
export function keyboardInset(v: ViewportSnapshot): KeyboardInset {
  const rest = { inset: 0, viewportHeight: Math.round(v.innerHeight) }
  if (!Number.isFinite(v.vvHeight) || v.vvHeight <= 0) return rest
  if (!Number.isFinite(v.scale) || Math.abs(v.scale - 1) >= SCALE_TOLERANCE) return rest
  const offset = Number.isFinite(v.vvOffsetTop) ? v.vvOffsetTop : 0
  const inset = Math.max(0, Math.round(v.innerHeight - v.vvHeight - offset))
  return { inset, viewportHeight: Math.round(v.vvHeight) }
}

/** CSS-переменные на `<html>`, которые читают шторки inline-стилем. */
export function keyboardCssVars(k: KeyboardInset): Record<string, string> {
  return { '--kb-inset': `${k.inset}px`, '--vv-height': `${k.viewportHeight}px` }
}
