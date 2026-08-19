import { describe, expect, it } from 'vitest'

import { contrast, labelChipColors, luminance } from './labelChip'

function ratio(a: string, b: string): number {
  const rgb = (h: string): [number, number, number] => {
    const n = parseInt(h.slice(1), 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  return contrast(luminance(rgb(a)), luminance(rgb(b)))
}

describe('labelChipColors', () => {
  // Три реальные метки тенанта + бирюзовый, который и заставил считать краску.
  it.each(['#E84393', '#00B4A8', '#5B9BD5', '#9B59B6', '#FFEB3B', '#000000'])(
    'даёт ≥4,5:1 для %s',
    (color) => {
      const { background, color: ink } = labelChipColors(color)
      expect(ratio(background, ink)).toBeGreaterThanOrEqual(4.5)
    },
  )

  it('не трогает цвет, который проходит как есть', () => {
    expect(labelChipColors('#E84393').background).toBe('#e84393')
  })

  it('затемняет тот, что не проходит ни с одной краской', () => {
    // #9B59B6 — 4,28:1 с тёмной и 4,11:1 со светлой.
    expect(labelChipColors('#9B59B6').background).not.toBe('#9b59b6')
  })

  it('переживает короткий hex, rgb() и мусор', () => {
    expect(labelChipColors('#abc').background).toBe('#aabbcc')
    expect(labelChipColors('rgb(232, 67, 147)').background).toBe('#e84393')
    for (const junk of ['', 'красный', '#zz', null, undefined]) {
      const c = labelChipColors(junk)
      expect(c.background).toMatch(/^#[0-9a-f]{6}$/)
      expect(ratio(c.background, c.color)).toBeGreaterThanOrEqual(4.5)
    }
  })
})
