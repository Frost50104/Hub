import { useEffect, useState, type RefObject } from 'react'

/** Размер элемента через ResizeObserver — ТВ-раскладка считает число дорожек
 *  и строк лидеров от реальной высоты слота, а не от констант. */
export function useElementSize<T extends HTMLElement>(ref: RefObject<T | null>): { width: number; height: number } {
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setSize({ width: r.width, height: r.height })
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) setSize({ width: entry.contentRect.width, height: entry.contentRect.height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return size
}
