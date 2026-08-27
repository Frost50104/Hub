import { useEffect, useState } from 'react'

/**
 * Subscribes to a CSS media query.
 *
 * SSR-safe (returns `false` on first render when `window` is missing),
 * SW-update-safe (re-attaches listener if the SW replaces `matchMedia` —
 * not happening today, but the listener pattern is idempotent).
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined
    const mq = window.matchMedia(query)
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches)
    setMatches(mq.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [query])

  return matches
}

/**
 * Mobile vs desktop layout breakpoint.
 *
 * Bumped to `lg` (1024px) post-4.8 redesign — iPad portrait (768×1024) was
 * showing the desktop sidebar squashed against a too-narrow main panel.
 * Below 1024px we serve the Asana-style mobile layout with a bottom tab bar.
 */
export function useIsDesktop(): boolean {
  return useMediaQuery('(min-width: 1024px)')
}

/**
 * Тач-устройство: курсора, который «наводят», у него нет.
 *
 * Нужен там, где решение принимает JS, а не CSS: например, перестановка
 * колонок доски. Мышью колонку тащат за заголовок, а пальцем внутри
 * свайп-ленты это неудобно — на тач-устройствах в меню колонки остаются
 * «Левее»/«Правее». CSS-двойник этого правила — вариант `[@media(hover:none)]`.
 */
export function useIsTouch(): boolean {
  return useMediaQuery('(hover: none)')
}
