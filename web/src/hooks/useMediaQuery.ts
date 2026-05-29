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

/** Tailwind `md:` breakpoint — desktop layout >=768px. */
export function useIsDesktop(): boolean {
  return useMediaQuery('(min-width: 768px)')
}
