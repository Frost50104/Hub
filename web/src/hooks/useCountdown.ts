import { useEffect, useState } from 'react'

import { countdownParts, nextTickMs, type CountdownParts } from '@/lib/raceCountdown'

/**
 * Тик раз в секунду, только пока вкладка видна; на `visibilitychange`
 * пересчёт сразу — iOS PWA морозит таймеры в фоне (см. UpdateBanner).
 */
export function useCountdown(targetIso: string | null | undefined): CountdownParts | null {
  const [parts, setParts] = useState<CountdownParts | null>(() =>
    targetIso ? countdownParts(targetIso, Date.now()) : null,
  )

  useEffect(() => {
    if (!targetIso) {
      setParts(null)
      return
    }
    let timer: number | null = null
    const tick = () => {
      const now = Date.now()
      setParts(countdownParts(targetIso, now))
      if (document.visibilityState === 'visible') {
        timer = window.setTimeout(tick, nextTickMs(now))
      } else {
        timer = null
      }
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible' && timer === null) tick()
    }
    tick()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      if (timer !== null) window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [targetIso])

  return parts
}
