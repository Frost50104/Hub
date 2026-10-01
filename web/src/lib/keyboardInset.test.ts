import { describe, expect, it } from 'vitest'

import { keyboardCssVars, keyboardInset } from './keyboardInset'

const snap = (innerHeight: number, vvHeight: number, vvOffsetTop: number, scale = 1) => ({
  innerHeight,
  vvHeight,
  vvOffsetTop,
  scale,
})

describe('keyboardInset', () => {
  it('в покое — ноль', () => {
    expect(keyboardInset(snap(844, 844, 0))).toEqual({ inset: 0, viewportHeight: 844 })
  })

  it('клавиатура наложилась, iOS не панорамировал — inset = её высота', () => {
    expect(keyboardInset(snap(844, 510, 0))).toEqual({ inset: 334, viewportHeight: 510 })
  })

  it('iOS полностью панорамировал viewport к полю — шторка и так видна', () => {
    expect(keyboardInset(snap(844, 510, 334))).toEqual({ inset: 0, viewportHeight: 510 })
  })

  it('частичное панорамирование — остаток', () => {
    expect(keyboardInset(snap(844, 510, 100)).inset).toBe(234)
  })

  it('дробные значения округляются', () => {
    expect(keyboardInset(snap(844, 509.6, 0.4)).inset).toBe(334)
  })

  it('visual viewport больше layout (переход тулбаров Safari) — не отрицательный', () => {
    expect(keyboardInset(snap(660, 750, 0))).toEqual({ inset: 0, viewportHeight: 750 })
  })

  it('зум — клавиатуры нет, потолок по layout viewport', () => {
    expect(keyboardInset(snap(844, 300, 120, 2.5))).toEqual({ inset: 0, viewportHeight: 844 })
  })

  it('scale 1.000001 — как единица', () => {
    expect(keyboardInset(snap(844, 510, 0, 1.000001)).inset).toBe(334)
  })

  it('нет высоты visual viewport — покой', () => {
    expect(keyboardInset(snap(844, 0, 0))).toEqual({ inset: 0, viewportHeight: 844 })
    expect(keyboardInset(snap(844, Number.NaN, 0))).toEqual({ inset: 0, viewportHeight: 844 })
  })

  it('полоса-аксессуар внешней клавиатуры (44pt) не прячется мёртвой зоной', () => {
    expect(keyboardInset(snap(844, 800, 0)).inset).toBe(44)
  })
})

describe('keyboardCssVars', () => {
  it('пишет обе переменные в пикселях', () => {
    expect(keyboardCssVars({ inset: 334, viewportHeight: 510 })).toEqual({
      '--kb-inset': '334px',
      '--vv-height': '510px',
    })
  })
})
