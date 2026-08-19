import { useCallback, useEffect, useState } from 'react'

/**
 * Прогресс чтения и позиция скролла — из ФАКТИЧЕСКОГО скролл-контейнера.
 *
 * В приложении их два (Shell.tsx): на десктопе (≥lg) корень —
 * `h-screen overflow-hidden`, и скроллится только `<main>`; на мобильном
 * скроллится документ. Поэтому `window.scrollY` молча врёт на десктопе, а
 * `main.scrollTop` — на мобильном: контейнер нужно искать от самого элемента
 * вверх по предкам.
 */
function findScrollParent(node: HTMLElement | null): HTMLElement | Window {
  let el = node?.parentElement ?? null
  while (el) {
    const { overflowY } = getComputedStyle(el)
    if ((overflowY === 'auto' || overflowY === 'scroll') && el.scrollHeight > el.clientHeight) {
      return el
    }
    el = el.parentElement
  }
  return window
}

function readProgress(target: HTMLElement | Window): { pct: number; top: number } {
  if (target === window) {
    const doc = document.documentElement
    const max = doc.scrollHeight - doc.clientHeight
    const top = window.scrollY
    return { pct: max > 0 ? Math.min(100, Math.max(0, (top / max) * 100)) : 0, top }
  }
  const el = target as HTMLElement
  const max = el.scrollHeight - el.clientHeight
  return {
    pct: max > 0 ? Math.min(100, Math.max(0, (el.scrollTop / max) * 100)) : 0,
    top: el.scrollTop,
  }
}

export interface ScrollProgress {
  /** Ref на любой узел ВНУТРИ скроллируемой области. */
  ref: (node: HTMLElement | null) => void
  /** Процент прочитанного, 0-100. */
  pct: number
  /** Позиция скролла в пикселях — для порога появления мини-шапки. */
  top: number
}

export function useScrollProgress(): ScrollProgress {
  const [pct, setPct] = useState(0)
  const [top, setTop] = useState(0)
  const [target, setTarget] = useState<HTMLElement | Window | null>(null)

  const ref = useCallback((node: HTMLElement | null) => {
    if (node) setTarget(findScrollParent(node))
  }, [])

  useEffect(() => {
    if (!target) return undefined
    // Меряем синхронно: два чтения свойств на событие, React их батчит.
    // Через requestAnimationFrame с флагом «кадр уже запланирован» хук
    // заклинивал намертво — если первый кадр не выполнялся (скрытая вкладка,
    // троттлинг), флаг оставался взведённым и прогресс не считался больше
    // никогда.
    const measure = () => {
      const next = readProgress(target)
      setPct(next.pct)
      setTop(next.top)
    }
    measure()
    target.addEventListener('scroll', measure, { passive: true })
    window.addEventListener('resize', measure)
    return () => {
      target.removeEventListener('scroll', measure)
      window.removeEventListener('resize', measure)
    }
  }, [target])

  return { ref, pct, top }
}
