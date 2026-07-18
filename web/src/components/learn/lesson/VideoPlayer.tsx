import { useCallback, useEffect, useRef, useState } from 'react'

import { authClient } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { learnApi } from '@/lib/learn'

/**
 * Видео урока (Ф3a): учёт реально просмотренных интервалов.
 *
 * - playsinline: iOS уходит в нативный фулскрин и игнорирует кастомный UI;
 * - пинг прогресса раз в 15с — шлём ПОЛНЫЙ merged-список интервалов, сервер
 *   мёржит идемпотентно (повтор не вредит, потеря пинга не теряет историю);
 * - flush на pagehide/visibilitychange — fetch keepalive с Bearer (iOS PWA
 *   фризит таймеры при блокировке экрана; sendBeacon не умеет заголовки);
 * - disableSeek: перемотка вперёд дальше просмотренного откатывается
 *   (deterrence — серверная проверка покрытия ≥90% остаётся главной).
 */

const PING_INTERVAL_MS = 15_000
const SEEK_JUMP_THRESHOLD = 2 // секунд разрыва = новый интервал
const GAP_CLOSE = 0.5 // локальный мёрж — та же щель, что на сервере

type Interval = [number, number]

function mergeLocal(intervals: Interval[]): Interval[] {
  const sorted = intervals
    .filter(([s, e]) => e > s && s >= 0)
    .sort((a, b) => a[0] - b[0])
  const merged: Interval[] = []
  for (const [s, e] of sorted) {
    const last = merged[merged.length - 1]
    if (last && s <= last[1] + GAP_CLOSE) last[1] = Math.max(last[1], e)
    else merged.push([s, e])
  }
  return merged
}

function coverageOf(intervals: Interval[], duration: number): number {
  if (duration <= 0) return 0
  const watched = intervals.reduce((acc, [s, e]) => acc + (e - s), 0)
  return Math.min(1, watched / duration)
}

export function VideoPlayer({
  lessonId,
  mediaId,
  src,
  requireFullWatch = false,
  disableSeek = false,
  initialIntervals = [],
  onCoverageChange,
  className,
}: {
  lessonId: string
  mediaId: string
  src: string
  requireFullWatch?: boolean
  disableSeek?: boolean
  initialIntervals?: Interval[]
  onCoverageChange?: (coverage: number) => void
  className?: string
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const intervalsRef = useRef<Interval[]>(mergeLocal(initialIntervals))
  const segStartRef = useRef<number | null>(null)
  const lastTimeRef = useRef(0)
  const maxReachedRef = useRef(
    intervalsRef.current.reduce((acc, [, e]) => Math.max(acc, e), 0),
  )
  const durationRef = useRef(0)
  const tokenRef = useRef<string | null>(null)
  const dirtyRef = useRef(false)
  const [coverage, setCoverage] = useState(() =>
    coverageOf(intervalsRef.current, 0),
  )

  const snapshot = useCallback((): Interval[] => {
    const current: Interval[] = [...intervalsRef.current]
    const seg = segStartRef.current
    const now = videoRef.current?.currentTime ?? lastTimeRef.current
    if (seg !== null && now > seg) current.push([seg, now])
    return mergeLocal(current)
  }, [])

  const refreshCoverage = useCallback(() => {
    const merged = snapshot()
    const c = coverageOf(merged, durationRef.current)
    setCoverage(c)
    onCoverageChange?.(c)
  }, [snapshot, onCoverageChange])

  const closeSegment = useCallback(() => {
    const seg = segStartRef.current
    if (seg === null) return
    const end = videoRef.current?.currentTime ?? lastTimeRef.current
    if (end > seg) {
      intervalsRef.current = mergeLocal([...intervalsRef.current, [seg, end]])
      dirtyRef.current = true
    }
    segStartRef.current = null
    refreshCoverage()
  }, [refreshCoverage])

  const flush = useCallback(async () => {
    if (!dirtyRef.current && segStartRef.current === null) return
    const merged = snapshot()
    if (!merged.length || durationRef.current <= 0) return
    dirtyRef.current = false
    try {
      await learnApi.reportVideoProgress(lessonId, {
        media_id: mediaId,
        intervals: merged,
        duration: durationRef.current,
      })
    } catch {
      dirtyRef.current = true // не потеряли — уйдёт со следующим пингом
    }
  }, [lessonId, mediaId, snapshot])

  // Кэш Bearer для keepalive-флаша: pagehide не дождётся async-получения.
  useEffect(() => {
    let alive = true
    const refresh = () => {
      void authClient.getAccessToken().then((t) => {
        if (alive) tokenRef.current = t
      })
    }
    refresh()
    const id = setInterval(refresh, PING_INTERVAL_MS * 4)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    const id = setInterval(() => void flush(), PING_INTERVAL_MS)
    return () => clearInterval(id)
  }, [flush])

  // Flush при уходе со страницы/сворачивании — keepalive переживает unload.
  useEffect(() => {
    const flushKeepalive = () => {
      const merged = snapshot()
      if (!merged.length || durationRef.current <= 0 || !tokenRef.current) return
      void fetch(`/api/learn/lessons/${lessonId}/video-progress`, {
        method: 'POST',
        keepalive: true,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokenRef.current}`,
          'X-Auth-Mode': 'api',
        },
        body: JSON.stringify({
          media_id: mediaId,
          intervals: merged,
          duration: durationRef.current,
        }),
      }).catch(() => undefined)
    }
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') flushKeepalive()
    }
    window.addEventListener('pagehide', flushKeepalive)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('pagehide', flushKeepalive)
      document.removeEventListener('visibilitychange', onVisibility)
      flushKeepalive() // размонтирование (переход между уроками)
    }
  }, [lessonId, mediaId, snapshot])

  const onTimeUpdate = () => {
    const video = videoRef.current
    if (!video || video.paused || video.seeking) return
    const t = video.currentTime
    if (segStartRef.current === null) {
      segStartRef.current = t
    } else if (Math.abs(t - lastTimeRef.current) > SEEK_JUMP_THRESHOLD) {
      // Разрыв (перемотка) — закрываем интервал по последней позиции.
      const seg = segStartRef.current
      if (lastTimeRef.current > seg) {
        intervalsRef.current = mergeLocal([
          ...intervalsRef.current,
          [seg, lastTimeRef.current],
        ])
        dirtyRef.current = true
      }
      segStartRef.current = t
    }
    lastTimeRef.current = t
    maxReachedRef.current = Math.max(maxReachedRef.current, t)
    refreshCoverage()
  }

  const onSeeking = () => {
    const video = videoRef.current
    if (!video || !disableSeek) return
    const allowed = Math.max(maxReachedRef.current, lastTimeRef.current) + 1
    if (video.currentTime > allowed) {
      video.currentTime = Math.min(allowed, lastTimeRef.current)
    }
  }

  const pct = Math.round(coverage * 100)

  return (
    <figure className={cn('my-3', className)}>
      <video
        ref={videoRef}
        src={src}
        controls
        playsInline
        preload="metadata"
        controlsList={disableSeek ? 'nodownload noplaybackrate' : 'nodownload'}
        className="w-full rounded-lg border border-glass-border bg-black"
        onLoadedMetadata={(e) => {
          durationRef.current = e.currentTarget.duration || 0
          refreshCoverage()
        }}
        onTimeUpdate={onTimeUpdate}
        onSeeking={onSeeking}
        onPause={closeSegment}
        onEnded={closeSegment}
        onWaiting={closeSegment}
      />
      {requireFullWatch && (
        <figcaption className="mt-1 flex items-center gap-2 text-xs text-text3">
          <span
            className={cn(
              'inline-block h-1.5 w-24 overflow-hidden rounded-full bg-glass',
            )}
          >
            <span
              className={cn('block h-full rounded-full', pct >= 90 ? 'bg-green' : 'bg-amber')}
              style={{ width: `${pct}%` }}
            />
          </span>
          {pct >= 90
            ? 'Видео досмотрено'
            : `Обязательно к просмотру — ${pct}% из 90%`}
        </figcaption>
      )}
    </figure>
  )
}
