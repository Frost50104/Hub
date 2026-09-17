import { useEffect, useState, type ReactNode } from 'react'

import { cn } from '@/lib/cn'

import '@/styles/race.css'

/**
 * Корень доски: скоуп CSS-переменных палитры гонки. `tv` — ТВ-раскладка
 * (крупный кегль, форс тёмной темы). Пока вкладка скрыта, анимации гусей и
 * конфетти ставятся на паузу — 63 дорожки в фоне не должны греть телефон.
 */
export function RaceBoard({ tv = false, className, children }: { tv?: boolean; className?: string; children: ReactNode }) {
  const [hidden, setHidden] = useState(() => typeof document !== 'undefined' && document.hidden)
  useEffect(() => {
    const onVis = () => setHidden(document.hidden)
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])
  return (
    <div
      className={cn('race-board', tv && 'race-board--tv', hidden && 'race-board--paused', className)}
      data-theme={tv ? 'dark' : undefined}
    >
      {children}
    </div>
  )
}
