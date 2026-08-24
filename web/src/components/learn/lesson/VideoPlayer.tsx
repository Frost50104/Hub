import { Check } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { authClient } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { learnApi } from '@/lib/learn'
import {
  FLUSH_MESSAGES,
  MAX_INTERVALS,
  bodySignature,
  buildWatchView,
  capIntervals,
  classifyFlushError,
  countsAsWatched,
  displayPercent,
  formatClock,
  isWatched,
  parseEcho,
  pickDuration,
  sameWatchView,
  serverCoverageFloor,
  type FlushOutcome,
  type Interval,
  type VideoProgressEcho,
  type WatchView,
} from '@/lib/videoWatch'

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
const pendingByLesson = new Map<string, Set<() => Promise<FlushOutcome>>>()

/** Порядок «плохости»: худший исход и решает, что показать человеку. */
const OUTCOME_RANK: Record<FlushOutcome, number> = {
  ok: 0,
  retry: 1,
  state: 2,
  auth: 3,
  poison: 4,
}

/**
 * Дослать прогресс всех видео урока и вернуть ХУДШИЙ исход.
 *
 * Раньше ошибка отправки тут терялась: `flush` её глотал, `await` спокойно
 * резолвился, и завершение урока судилось по устаревшим интервалам — человек
 * получал 409 «досмотрите видео до конца» вместо «прогресс не доехал».
 */
export async function flushVideoProgress(lessonId: string): Promise<FlushOutcome> {
  const flushes = pendingByLesson.get(lessonId)
  if (!flushes) return 'ok'
  const results = await Promise.all([...flushes].map((fn) => fn()))
  return results.reduce<FlushOutcome>(
    (worst, cur) => (OUTCOME_RANK[cur] > OUTCOME_RANK[worst] ? cur : worst),
    'ok',
  )
}

/** Текст для человека по исходу отправки (для `ok` текста нет). */
export function flushMessage(outcome: FlushOutcome): string | null {
  return outcome === 'ok' ? null : FLUSH_MESSAGES[outcome]
}

/** Статус ответа из ошибки axios; `null` — ответа не было вовсе. */
function statusOf(err: unknown): number | null {
  const status = (err as { response?: { status?: unknown } })?.response?.status
  return typeof status === 'number' ? status : null
}

export function VideoPlayer({
  lessonId,
  mediaId,
  src,
  requireFullWatch = false,
  disableSeek = false,
  initialIntervals = [],
  initialDuration = null,
  preview = false,
  onCoverageChange,
  className,
}: {
  lessonId: string
  mediaId: string
  src: string
  requireFullWatch?: boolean
  disableSeek?: boolean
  initialIntervals?: Interval[]
  /** Длительность из block_state — сервер её знает из файла (0043). */
  initialDuration?: number | null
  /** Превью черновика: прогресса у автора нет, ручка ответит 409 на каждый
   *  пинг. В этом режиме не шлём вовсе. */
  preview?: boolean
  onCoverageChange?: (coverage: number) => void
  className?: string
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  // Подписанный URL медиа переиздаётся при каждом ответе урока, а смена
  // атрибута `src` перезагружает элемент: позиция слетает на 0, воспроизведение
  // встаёт на паузу. С `staleTime: 0` у урока это случалось бы при каждом
  // возврате во вкладку. Ссылка живёт часами, ролик уже играет по ней — держим
  // ту, с которой стартовали (другое видео получает новый инстанс: `key`
  // включает `mediaId`).
  const srcRef = useRef(src)
  // Просмотренное копится микро-интервалами [prev, now] между timeupdate —
  // модель без «открытых сегментов» переживает waiting/паузы/буферизацию,
  // из-за которых сегментная версия теряла куски.
  const intervalsRef = useRef<Interval[]>(
    capIntervals(initialIntervals, MAX_INTERVALS, initialDuration ?? 0),
  )
  const lastTimeRef = useRef(0)
  const maxReachedRef = useRef(
    intervalsRef.current.reduce((acc, [, e]) => Math.max(acc, e), 0),
  )
  const durationRef = useRef(initialDuration ?? 0)
  const tokenRef = useRef<string | null>(null)
  const dirtyRef = useRef(false)
  const seekedRef = useRef(false)
  // «Отравлено»: сервер отказал так, что повтор ТОГО ЖЕ тела бессмыслен.
  // Без этого ближайший timeupdate снова ставил dirty, и цикл 422 крутился
  // раз в 15 секунд до конца сессии.
  const poisonedRef = useRef(false)
  const outcomeRef = useRef<FlushOutcome>('ok')
  // Подпись последней ушедшей отправки: на iOS pagehide и visibilitychange
  // приходят оба, и второй запрос был бы ровно тем же телом.
  const sentRef = useRef('')
  const aliveRef = useRef(true)
  // Покрытие, подтверждённое сервером (эхо ручки). Монотонно: пинг и
  // keepalive-флаш летят одновременно, ответы приходят в любом порядке, и без
  // max() полоса прыгала бы назад на устаревшем эхе.
  const serverCoverageRef = useRef(0)
  const [view, setView] = useState<WatchView>(() =>
    buildWatchView(intervalsRef.current, initialDuration ?? 0, 0),
  )
  const [meta, setMeta] = useState(() => ({
    durationKnown: (initialDuration ?? 0) > 0,
    hasIntervals: intervalsRef.current.length > 0,
  }))
  // Провал отправки раньше гасился молча: на экране это неотличимо от
  // «не досмотрел», и человек пересматривал ролик вместо того, чтобы
  // проверить связь.
  const [saveState, setSaveState] = useState<'ok' | 'retrying' | 'poisoned'>('ok')

  // Проп-колбэк живёт в ref: иначе `refreshCoverage` меняет идентичность на
  // каждый рендер, а за ней — `flush` и эффекты, которые от неё зависят. Эффект
  // keepalive при пересоздании выполняет cleanup, то есть ШЛЁТ запрос: на проде
  // это давало 12 отправок за 2,5 секунды воспроизведения (по одной на
  // timeupdate), каждая — запись в БД под FOR UPDATE. Плюс пинговый interval
  // пересоздавался и до своих 15 секунд не доживал вовсе.
  const onCoverageRef = useRef(onCoverageChange)
  useEffect(() => {
    onCoverageRef.current = onCoverageChange
  })

  const unpoison = useCallback(() => {
    if (!poisonedRef.current) return
    poisonedRef.current = false
    outcomeRef.current = 'ok'
    setSaveState('ok')
  }, [])

  const snapshot = useCallback((): Interval[] => {
    const before = intervalsRef.current.length
    intervalsRef.current = capIntervals(
      intervalsRef.current,
      MAX_INTERVALS,
      durationRef.current,
    )
    // Список ужался — тело отправки изменилось, значит прежний отказ по
    // размеру больше не воспроизводится.
    if (intervalsRef.current.length < before) unpoison()
    return intervalsRef.current
  }, [unpoison])

  const refreshCoverage = useCallback(() => {
    const merged = snapshot()
    const next = buildWatchView(merged, durationRef.current, serverCoverageRef.current)
    setView((prev) => (sameWatchView(prev, next) ? prev : next))
    const durationKnown = durationRef.current > 0
    const hasIntervals = merged.length > 0
    setMeta((prev) =>
      prev.durationKnown === durationKnown && prev.hasIntervals === hasIntervals
        ? prev
        : { durationKnown, hasIntervals },
    )
    onCoverageRef.current?.(next.coverage)
  }, [snapshot])

  const applyDuration = useCallback(
    (next: number) => {
      if (next <= 0 || next === durationRef.current) return
      durationRef.current = next
      // Длительность резолвилась — причина прежнего отказа устранена.
      unpoison()
      refreshCoverage()
    },
    [refreshCoverage, unpoison],
  )

  /** Прочитать длительность у элемента: duration, иначе конец seekable. */
  const syncDuration = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    const ranges = video.seekable
    // `end(-1)` бросает IndexSizeError; на loadedmetadata length === 0 — норма.
    const end = ranges && ranges.length > 0 ? ranges.end(ranges.length - 1) : null
    applyDuration(pickDuration(video.duration, end))
  }, [applyDuration])

  const applyEcho = useCallback(
    (echo: VideoProgressEcho | null) => {
      if (!echo || !aliveRef.current) return
      let changed = false
      // Знаменатель — серверный: длительность он читает из самого файла, и
      // ровно на неё делит гейт. Своего мнения о ней у клиента больше нет —
      // отсюда и невозможность «полоса зелёная, а завершение 409».
      if (echo.duration && echo.duration !== durationRef.current) {
        durationRef.current = echo.duration
        changed = true
      }
      // И числитель тоже: сервер судит по СВОЕЙ копии интервалов, а клиент
      // стартует от снимка урока, который мог устареть. Пока эхо приносило
      // только длительность, разойтись они могли молча.
      const floor = serverCoverageFloor(echo)
      if (floor > serverCoverageRef.current) {
        serverCoverageRef.current = floor
        changed = true
      }
      if (changed) refreshCoverage()
    },
    [refreshCoverage],
  )

  const flush = useCallback(async (): Promise<FlushOutcome> => {
    if (poisonedRef.current) return 'poison'
    if (!dirtyRef.current) return outcomeRef.current
    const merged = snapshot()
    if (!merged.length) return 'ok'
    dirtyRef.current = false
    if (preview) return 'ok'
    const duration = durationRef.current > 0 ? durationRef.current : null
    try {
      const echo = await learnApi.reportVideoProgress(lessonId, {
        media_id: mediaId,
        intervals: merged,
        duration,
      })
      sentRef.current = bodySignature(merged, duration)
      applyEcho(echo)
      outcomeRef.current = 'ok'
      setSaveState('ok')
      return 'ok'
    } catch (err) {
      dirtyRef.current = true // не потеряли — уйдёт со следующим пингом
      const kind = classifyFlushError(statusOf(err))
      outcomeRef.current = kind
      if (kind === 'poison') {
        poisonedRef.current = true
        setSaveState('poisoned')
      } else {
        setSaveState('retrying')
      }
      return kind
    }
  }, [lessonId, mediaId, preview, snapshot, applyEcho])

  useEffect(
    () => () => {
      aliveRef.current = false
    },
    [],
  )

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
      if (preview || poisonedRef.current) return
      const merged = snapshot()
      if (!merged.length || !tokenRef.current) return
      const duration = durationRef.current > 0 ? durationRef.current : null
      const sig = bodySignature(merged, duration)
      if (sig === sentRef.current) return
      sentRef.current = sig
      // Остаёмся на fetch(keepalive): на iOS visibilitychange часто
      // предшествует заморозке вкладки, и обычный запрос там убивают, а
      // Authorization/X-Auth-Mode для PWA-режима beacon отправить не умеет.
      // Ответ при этом читаем — если страница выжила, промис резолвится.
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
          duration,
        }),
      })
        .then((res) => {
          if (!aliveRef.current) return
          if (!res.ok) {
            sentRef.current = ''
            const kind = classifyFlushError(res.status)
            outcomeRef.current = kind
            if (kind === 'poison') {
              poisonedRef.current = true
              setSaveState('poisoned')
            } else {
              setSaveState('retrying')
            }
            return
          }
          dirtyRef.current = false
          outcomeRef.current = 'ok'
          setSaveState('ok')
          return res
            .json()
            .then((data) => applyEcho(parseEcho(data)))
            .catch(() => undefined) // 204 от старого бэкенда — тела нет
        })
        .catch(() => {
          // Страница уходит — ответа не будет; данные останутся dirty.
          sentRef.current = ''
        })
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
  }, [lessonId, mediaId, preview, snapshot, applyEcho])

  const onTimeUpdate = () => {
    const video = videoRef.current
    if (!video || video.seeking) return
    const t = video.currentTime
    const last = lastTimeRef.current
    lastTimeRef.current = t
    // Перемотку опознаём по событию `seeking`, а не по размеру шага: браузер
    // душит `timeupdate` у фоновой вкладки и на слабом устройстве, и прежний
    // порог в 2 секунды выбрасывал честно проигранные куски (ОС 24.08).
    const seeked = seekedRef.current
    seekedRef.current = false
    if (countsAsWatched(last, t, seeked)) {
      intervalsRef.current.push([last, t])
      dirtyRef.current = true
      if (intervalsRef.current.length > MAX_INTERVALS) snapshot() // компактизация
    }
    maxReachedRef.current = Math.max(maxReachedRef.current, t)
    if (durationRef.current <= 0) syncDuration()
    refreshCoverage()
  }

  const onSeeking = () => {
    // Флаг живёт до ближайшего timeupdate: именно он отличает перемотку от
    // задушенного таймера.
    seekedRef.current = true
    const video = videoRef.current
    if (!video || !disableSeek) return
    const allowed = Math.max(maxReachedRef.current, lastTimeRef.current) + 1
    if (video.currentTime > allowed) {
      video.currentTime = Math.min(allowed, lastTimeRef.current)
    }
  }

  /**
   * Перейти к первому непросмотренному куску.
   *
   * Прыжок всегда назад или ровно на достигнутое, поэтому откат `disableSeek`
   * (`allowed = maxReached + 1`) его не трогает. Интервал от прыжка не
   * запишется: `onSeeking` поднимает флаг, и ближайший `timeupdate` шаг не
   * засчитает.
   */
  const jumpTo = (at: number) => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = at
    void video.play().catch(() => undefined)
  }

  const pct = displayPercent(view.coverage)
  const watched = isWatched(view.coverage)
  // Длительность неизвестна, а смотреть человек начал: гейт по-честному
  // закрыт (сервер ответит тем же), и молчать об этом нельзя — иначе на
  // экране вечные «сейчас 0%» без объяснения.
  const unmeasured = !meta.durationKnown && meta.hasIntervals
  // Ролик ещё не открывали: «К непросмотренному · 0:00» — шум, непросмотрено
  // всё. Подсказка появляется, когда есть что продолжать.
  const gap = watched || unmeasured || view.segments.length === 0 ? null : view.gap

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
        src={srcRef.current}
        controls
        playsInline
        preload="metadata"
        controlsList={disableSeek ? 'nodownload noplaybackrate' : 'nodownload'}
        className="block aspect-video w-full bg-[#08080E]"
        onLoadedMetadata={syncDuration}
        // Ровно то событие, ради которого оно и существует: duration была
        // Infinity (moov ещё не разобран), стала известна.
        onDurationChange={syncDuration}
        onTimeUpdate={onTimeUpdate}
        onSeeking={onSeeking}
        onPause={() => {
          refreshCoverage()
          void flush()
        }}
        onEnded={() => {
          // Ролик доигран: закрываем хвост от последнего тика до конца —
          // иначе последние доли секунды (а на паузе перед концом и больше)
          // не засчитывались, хотя человек досмотрел. Только при КОНЕЧНОЙ
          // длительности: [x, Infinity] давал NaN в покрытии и «сейчас NaN%».
          const end = durationRef.current
          if (Number.isFinite(end) && end > lastTimeRef.current && !seekedRef.current) {
            intervalsRef.current.push([lastTimeRef.current, end])
            lastTimeRef.current = end
            dirtyRef.current = true
          }
          refreshCoverage()
          void flush()
        }}
      />
      {requireFullWatch && (
        <>
          {/* Карта просмотра: закрашено ровно то, что засчитано, пропуски
              видны фоном. Одна заливка слева на N% врала — при пропуске в
              середине на экране горело «62%», а ползунок стоял в конце ролика,
              и понять причину было нечем (ОС 24.08). Не элемент управления:
              кликов не принимает, вид слайдера не изображает. `overflow-hidden`
              держит минимальную ширину куска внутри полосы. */}
          <div className="relative h-[3px] overflow-hidden bg-surface" aria-hidden>
            {view.segments.map((seg) => (
              <span
                key={seg.leftPct}
                className={cn(
                  'absolute inset-y-0 transition-[width] duration-300 ease-out',
                  watched ? 'bg-green' : 'bg-amber',
                )}
                style={{
                  left: `${seg.leftPct}%`,
                  width: `${seg.widthPct}%`,
                  minWidth: '2px',
                }}
              />
            ))}
          </div>
          <figcaption className="flex flex-wrap items-center gap-x-2.5 gap-y-2 px-3.5 py-3">
            <span
              className={cn(
                'flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full',
                watched
                  ? 'bg-green-deep text-bg'
                  : 'border border-glass-border text-transparent',
              )}
            >
              <Check className="h-[15px] w-[15px]" strokeWidth={2.4} />
            </span>
            <p className="min-w-0 flex-1 text-sm leading-[1.45] text-text2 lg:text-[15px]">
              {watched
                ? 'Видео досмотрено'
                : unmeasured
                  ? 'Не удалось определить длительность этого видео — завершить урок не выйдет. Сообщите администратору.'
                  : gap?.kind === 'skipped'
                    ? // Обвинять в перемотке того, кто просто не дошёл до конца,
                      // нельзя — этот текст только для дыры ВНУТРИ.
                      `Перемотка не засчитывается — вернитесь к пропущенному. Сейчас ${pct}%`
                    : `Досмотрите минимум 90% — сейчас ${pct}%`}
            </p>
            {gap && (
              <button
                type="button"
                onClick={() => jumpTo(gap.at)}
                className="shrink-0 rounded-lg border border-glass-border px-2.5 py-1.5 text-[13px] font-semibold leading-none text-text transition-colors hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              >
                К непросмотренному · {formatClock(gap.at)}
              </button>
            )}
          </figcaption>
        </>
      )}
      {saveState !== 'ok' && (
        <p className="border-t border-glass-border px-3.5 py-2.5 text-[13px] leading-[1.45] text-red">
          {saveState === 'retrying'
            ? 'Прогресс просмотра не сохранён — проверьте связь. Мы попробуем ещё раз сами; пока этого не случилось, урок завершить не выйдет.'
            : FLUSH_MESSAGES.poison}
        </p>
      )}
    </figure>
  )
}

