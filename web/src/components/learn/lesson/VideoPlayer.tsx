import { Check } from 'lucide-react'
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

/**
 * Незавершённые отправки прогресса по урокам.
 *
 * ОС 19.08 «видео не засчитывается сразу»: полоса покрытия зелёная (её считает
 * клиент), а «Завершить урок» отвечает 409 — сервер судит по интервалам,
 * которые уходят раз в 15 секунд. Досмотрев ролик, сотрудник жмёт кнопку
 * раньше ближайшего пинга и упирается в данные пятнадцатисекундной давности;
 * прогресс доезжал позже — на pagehide/visibilitychange, то есть «когда
 * погас экран». Поэтому завершение урока обязано сначала дослать прогресс.
 */
const pendingByLesson = new Map<string, Set<() => Promise<void>>>()

/** Дослать прогресс всех видео урока и дождаться ответа сервера. */
export async function flushVideoProgress(lessonId: string): Promise<void> {
  const flushes = pendingByLesson.get(lessonId)
  if (!flushes) return
  await Promise.all([...flushes].map((fn) => fn()))
}

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
  // Просмотренное копится микро-интервалами [prev, now] между timeupdate —
  // модель без «открытых сегментов» переживает waiting/паузы/буферизацию,
  // из-за которых сегментная версия теряла куски.
  const intervalsRef = useRef<Interval[]>(mergeLocal(initialIntervals))
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
  // Провал отправки раньше гасился молча: на экране это неотличимо от
  // «не досмотрел», и человек пересматривал ролик вместо того, чтобы
  // проверить связь.
  const [saveFailed, setSaveFailed] = useState(false)

  const snapshot = useCallback((): Interval[] => {
    intervalsRef.current = mergeLocal(intervalsRef.current)
    return intervalsRef.current
  }, [])

  const refreshCoverage = useCallback(() => {
    const c = coverageOf(snapshot(), durationRef.current)
    setCoverage(c)
    onCoverageChange?.(c)
  }, [snapshot, onCoverageChange])

  const flush = useCallback(async () => {
    if (!dirtyRef.current) return
    const merged = snapshot()
    if (!merged.length || durationRef.current <= 0) return
    dirtyRef.current = false
    try {
      await learnApi.reportVideoProgress(lessonId, {
        media_id: mediaId,
        intervals: merged,
        duration: durationRef.current,
      })
      setSaveFailed(false)
    } catch {
      dirtyRef.current = true // не потеряли — уйдёт со следующим пингом
      setSaveFailed(true)
    }
  }, [lessonId, mediaId, snapshot])

  // Регистрируемся в реестре урока, пока плеер на экране.
  useEffect(() => {
    let flushes = pendingByLesson.get(lessonId)
    if (!flushes) {
      flushes = new Set()
      pendingByLesson.set(lessonId, flushes)
    }
    const registry = flushes
    registry.add(flush)
    return () => {
      registry.delete(flush)
      if (registry.size === 0) pendingByLesson.delete(lessonId)
    }
  }, [lessonId, flush])

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
    if (!video || video.seeking) return
    const t = video.currentTime
    const last = lastTimeRef.current
    lastTimeRef.current = t
    // Шаг вперёд в пределах порога = реально просмотренный кусок;
    // больший скачок — перемотка, время не засчитывается.
    if (t > last && t - last <= SEEK_JUMP_THRESHOLD) {
      intervalsRef.current.push([last, t])
      dirtyRef.current = true
      if (intervalsRef.current.length > 200) snapshot() // компактизация
    }
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
    <figure
      className={cn(
        'my-7 overflow-hidden rounded-[14px] border border-glass-border bg-tint lg:my-8',
        className,
      )}
    >
      {/* Нативные controls остаются: iOS уходит в фулскрин и игнорирует
          кастомный UI, а свой плеер стоил бы доступности. Из макета берём
          оболочку — рамку, полосу покрытия и строку условия. */}
      <video
        ref={videoRef}
        src={src}
        controls
        playsInline
        preload="metadata"
        controlsList={disableSeek ? 'nodownload noplaybackrate' : 'nodownload'}
        className="block aspect-video w-full bg-[#08080E]"
        onLoadedMetadata={(e) => {
          durationRef.current = e.currentTarget.duration || 0
          refreshCoverage()
        }}
        onTimeUpdate={onTimeUpdate}
        onSeeking={onSeeking}
        onPause={() => {
          refreshCoverage()
          void flush()
        }}
        onEnded={() => {
          refreshCoverage()
          void flush()
        }}
      />
      {requireFullWatch && (
        <>
          {/* Полоса покрытия: амбер до порога, зелёный после. Порог считает
              сервер — полоса лишь отражает. disableSeek её не прячет. */}
          <div className="h-[3px] bg-surface">
            <div
              className={cn(
                'h-full transition-[width] duration-300 ease-out',
                pct >= 90 ? 'bg-green' : 'bg-amber',
              )}
              style={{ width: `${pct}%` }}
            />
          </div>
          <figcaption className="flex items-center gap-2.5 px-3.5 py-3">
            <span
              className={cn(
                'flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full',
                pct >= 90
                  ? 'bg-green-deep text-bg'
                  : 'border border-glass-border text-transparent',
              )}
            >
              <Check className="h-[15px] w-[15px]" strokeWidth={2.4} />
            </span>
            <p className="flex-1 text-sm leading-[1.45] text-text2 lg:text-[15px]">
              {pct >= 90
                ? 'Видео досмотрено'
                : `Досмотрите минимум 90% — сейчас ${pct}%`}
            </p>
          </figcaption>
        </>
      )}
      {saveFailed && (
        <p className="border-t border-glass-border px-3.5 py-2.5 text-[13px] leading-[1.45] text-red">
          Прогресс просмотра не сохранён — проверьте связь. Мы попробуем ещё раз
          сами; пока этого не случилось, урок завершить не выйдет.
        </p>
      )}
    </figure>
  )
}
