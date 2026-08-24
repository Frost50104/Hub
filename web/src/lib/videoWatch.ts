/**
 * Учёт просмотренного времени видео — чистая часть плеера.
 *
 * Модель та же, что на сервере (`app/services/video_progress.py`): множество
 * интервалов `[start, end]`, покрытие = длина объединения к длительности,
 * порог — `WATCH_THRESHOLD`. Здесь только правила накопления; отправку и
 * события DOM держит `components/learn/lesson/VideoPlayer.tsx`.
 */

import { WATCH_THRESHOLD } from './lessonGates'

export type Interval = [number, number]

/**
 * Щель короче — считаем одним куском. Та же, что на сервере
 * (`GAP_CLOSE_SEC` в `app/services/video_progress.py`): разойдутся константы —
 * разойдутся процент на экране и вердикт гейта.
 *
 * Полсекунды не хватало. После перемотки первый шаг всегда теряется
 * (`seekedRef` съедает ближайший `timeupdate`), плюс `timeupdate` душат в
 * фоне — в записи оставались микро-дыры на 1–2 секунды. Человек их не
 * пропускал, а проценты недобирал: на проде у одного ролика ровно две такие,
 * 1.9 с и 1.0 с.
 */
export const GAP_CLOSE = 2

export function mergeIntervals(intervals: readonly Interval[]): Interval[] {
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

export function coverageOf(intervals: readonly Interval[], duration: number): number {
  if (duration <= 0) return 0
  const watched = intervals.reduce((acc, [s, e]) => acc + (e - s), 0)
  return Math.min(1, watched / duration)
}

/** Досмотрено ли — сравниваем ТАК ЖЕ, как сервер, без округления. */
export function isWatched(coverage: number): boolean {
  return coverage >= WATCH_THRESHOLD
}

/**
 * Процент для показа. Округляем ВНИЗ: `Math.round` зеленил полосу с 89,5%,
 * а сервер в этот момент отвечал 409 «досмотрите видео» — цифра на экране
 * не должна обещать больше, чем засчитает гейт.
 */
export function displayPercent(coverage: number): number {
  return Math.floor(coverage * 100)
}

/**
 * Засчитывать ли шаг воспроизведения `from → to`.
 *
 * Раньше правилом был порог в 2 секунды: любой скачок больше — «перемотка».
 * Но `timeupdate` душат и без перемотки — фоновая вкладка (Chrome до 1/сек и
 * реже), слабое устройство, ребуферизация; видео при этом честно играет, а
 * секунды молча не засчитывались, и добрать их можно было только повторным
 * просмотром ровно этого куска. Признак перемотки — событие `seeking`, а не
 * размер шага.
 */
export function countsAsWatched(from: number, to: number, seeked: boolean): boolean {
  return to > from && !seeked
}

/** Кусок полосы просмотра в процентах ширины. */
export interface WatchSegment {
  leftPct: number
  widthPct: number
}

/**
 * Карта просмотра для полосы под плеером.
 *
 * Раньше полоса была ОДНОЙ заливкой слева на N%: при пропуске в середине на
 * экране горело «62%», а ползунок стоял в конце ролика — увидеть, ЧТО именно
 * не засчитано, было нечем, и это читалось как поломка (ОС 24.08). Сегменты
 * показывают дыру там, где она есть.
 *
 * Сумма ширин равна покрытию: минимальную видимую ширину куска добавляет CSS,
 * а не эта функция, иначе число под полосой перестало бы сходиться с ней.
 */
export function watchSegments(
  intervals: readonly Interval[],
  duration: number,
): WatchSegment[] {
  if (!(duration > 0)) return []
  const out: WatchSegment[] = []
  for (const [start, end] of mergeIntervals(intervals)) {
    const left = Math.min(100, Math.max(0, (start / duration) * 100))
    const right = Math.min(100, Math.max(0, (end / duration) * 100))
    if (right <= left) continue
    out.push({ leftPct: left, widthPct: right - left })
  }
  return out
}

/** Первая значимая дыра: где продолжить и что это за пропуск. */
export interface WatchGap {
  /** Секунда, с которой стоит продолжить просмотр. */
  at: number
  /**
   * `tail` — просто не досмотрел до конца, `skipped` — пропуск внутри (или
   * начало): человек перематывал. Обвинять в перемотке того, кто честно не
   * дошёл до конца, нельзя — тексты для этих случаев разные.
   */
  kind: 'skipped' | 'tail'
}

/**
 * Найти первую дыру длиннее `minGap`, включая хвостовую `[конец, duration]`.
 *
 * Хвост обязателен: «не досмотрел концовку» — самый частый случай, и молчать
 * там, где подсказка нужнее всего, было бы странно. Дыры короче склейки не
 * считаются: прыгать на пропуск, невидимый глазу, некуда.
 */
export function firstGap(
  intervals: readonly Interval[],
  duration: number,
  minGap: number = GAP_CLOSE,
): WatchGap | null {
  if (!(duration > 0)) return null
  let cursor = 0
  for (const [start, end] of mergeIntervals(intervals)) {
    if (start >= duration) break
    if (start - cursor >= minGap) return { at: cursor, kind: 'skipped' }
    cursor = Math.max(cursor, end)
  }
  if (duration - cursor >= minGap) return { at: cursor, kind: 'tail' }
  return null
}

/**
 * Насколько серверное покрытие может превысить локальное, оставаясь «тем же».
 *
 * Ручка округляет `coverage` до 4 знаков, поэтому серверное число превышает
 * локальное почти всегда — на тысячные доли процента. Полпроцента — заведомо
 * не «второе устройство»: с порогом 1e-6 подсказка «к непросмотренному»
 * пропадала сразу после первого же пинга (staging, 25.08).
 */
export const COVERAGE_SLACK = 0.005

/** Всё, что рисуется под плеером, одним снимком. */
export interface WatchView {
  /** Показываемое покрытие: max(локальное, подтверждённое сервером). */
  coverage: number
  /** Карта просмотра: закрашенные куски полосы. */
  segments: WatchSegment[]
  /** Куда предложить вернуться; `null` — предлагать нечего или незачем. */
  gap: WatchGap | null
}

/**
 * Собрать вид полосы по локальным интервалам и серверному покрытию.
 *
 * Число — `max`: между пингами больше локальное (неотправленные секунды), а
 * после возврата в урок по устаревшему снимку — серверное; «показывать
 * серверное» в лоб откатывало бы полосу назад каждые 15 секунд.
 *
 * Карта строится только из ЛОКАЛЬНЫХ интервалов — эхо ручки их не возвращает.
 * Поэтому если сервер знает ЗАМЕТНО больше (второе устройство, устаревший
 * снимок урока), звать «к непросмотренному» нельзя: мы не знаем, что именно
 * осталось, и отправили бы пересматривать уже засчитанное.
 */
export function buildWatchView(
  intervals: readonly Interval[],
  duration: number,
  serverCoverage: number,
): WatchView {
  const local = coverageOf(intervals, duration)
  return {
    coverage: Math.max(local, serverCoverage),
    segments: watchSegments(intervals, duration),
    gap: serverCoverage <= local + COVERAGE_SLACK ? firstGap(intervals, duration) : null,
  }
}

/** Изменилось ли то, что видно на экране (лишние ре-рендеры не нужны). */
export function sameWatchView(a: WatchView, b: WatchView): boolean {
  return (
    a.coverage === b.coverage &&
    a.segments.length === b.segments.length &&
    a.gap?.at === b.gap?.at &&
    a.gap?.kind === b.gap?.kind
  )
}

/** `95` секунд → `1:35`. Для подписи кнопки «продолжить с …». */
export function formatClock(seconds: number): string {
  // `Math.max(0, NaN)` — это NaN: без явной проверки на подписи кнопки
  // загорелось бы «NaN:NaN».
  const total = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0
  const mm = Math.floor(total / 60)
  const ss = total % 60
  return `${mm}:${String(ss).padStart(2, '0')}`
}

/**
 * Сколько интервалов клиент готов держать и слать.
 *
 * Столько же хранит сервер (`MAX_INTERVALS` в `video_progress.py`), а
 * принимает вдвое больше — так что переполнение никогда не превращается в 422.
 */
export const MAX_INTERVALS = 500

/** Короче — артефакт скраббинга, а не просмотр. Та же граница, что на сервере. */
export const MIN_INTERVAL_SEC = 0.25

/** Бюджет «склейки щелей» при переполнении — доля длительности. */
const GAP_BUDGET_RATIO = 0.01

/**
 * Какое число считать длительностью ролика.
 *
 * `video.duration` бывает `Infinity` (пока не пришёл moov, а у части
 * мобильных Safari — и дольше) и `NaN` (метаданные не разобрались). Прежний
 * код клал это как есть: `Infinity` уходил в JSON как `null` и ловил 422 на
 * каждом пинге, а после вчерашней правки хвоста давал ещё и «сейчас NaN%».
 * Запасной вариант — конец `seekable`: браузер знает его раньше, чем
 * длительность.
 */
export function pickDuration(raw: number, seekableEnd: number | null): number {
  if (Number.isFinite(raw) && raw > 0) return raw
  if (seekableEnd != null && Number.isFinite(seekableEnd) && seekableEnd > 0) {
    return seekableEnd
  }
  return 0
}

/** Что делать с неудачной отправкой прогресса. */
export type FlushOutcome = 'ok' | 'retry' | 'poison' | 'state' | 'auth'

/**
 * Разобрать неудачу отправки. `null` — ответа не было вовсе (сеть, unload).
 *
 * `poison` означает «повтор того же тела не поможет»: молча ретраить такое —
 * это бесконечный цикл записей в БД и вечно красный баннер без объяснения.
 */
export function classifyFlushError(status: number | null): FlushOutcome {
  if (status === null || status === 0) return 'retry'
  if (status >= 500 || status === 408 || status === 429) return 'retry'
  if (status === 401 || status === 403) return 'auth'
  if (status === 404 || status === 409) return 'state'
  return 'poison'
}

/** Тексты для человека — по исходу отправки. */
export const FLUSH_MESSAGES: Record<Exclude<FlushOutcome, 'ok'>, string> = {
  retry: 'Прогресс просмотра не доехал до сервера — проверьте связь и попробуйте ещё раз.',
  poison: 'Сервер не принял прогресс просмотра. Обновите страницу; если не поможет — сообщите администратору.',
  state: 'Урок открыт в другом месте или изменился — обновите страницу.',
  auth: 'Сессия истекла — войдите заново.',
}

/**
 * Подпись тела отправки — чтобы не слать дважды одно и то же.
 *
 * В неё обязана входить СУММА просмотренного, а не только количество кусков и
 * конец последнего: заполняя дыру в середине (сценарий «вернулся и досматриваю
 * пропущенное»), человек не меняет ни то, ни другое — и уходной флаш на
 * `pagehide` считал тело дубликатом и МОЛЧА его не слал. Секунды между
 * пятнадцатисекундными пингами при уходе со страницы терялись.
 */
export function bodySignature(
  intervals: readonly Interval[],
  duration: number | null,
): string {
  let covered = 0
  for (const [start, end] of intervals) covered += end - start
  const last = intervals[intervals.length - 1]
  return `${intervals.length}:${covered.toFixed(3)}:${last ? last[1] : 0}:${duration ?? 'x'}`
}

/** Ответ ручки прогресса: серверное покрытие и длительность из файла. */
export interface VideoProgressEcho {
  coverage: number
  duration: number | null
  watched: boolean
}

/**
 * Какое покрытие сервер подтвердил этим ответом.
 *
 * Обычно это просто `coverage`, но вердикт `watched` сильнее числа: считает
 * его та же формула, и если она когда-нибудь разойдётся, на экране обязано
 * остаться «досмотрено», а не «сейчас 89%» при зелёном гейте.
 */
export function serverCoverageFloor(echo: VideoProgressEcho): number {
  return echo.watched ? Math.max(echo.coverage, WATCH_THRESHOLD) : echo.coverage
}

/**
 * Разобрать эхо ручки. `null` — тела нет (бэкенд ещё старый, отвечает 204):
 * в окне деплоя новый бандл обязан это пережить.
 */
export function parseEcho(data: unknown): VideoProgressEcho | null {
  if (!data || typeof data !== 'object') return null
  const raw = data as Record<string, unknown>
  if (typeof raw.coverage !== 'number' || typeof raw.watched !== 'boolean') return null
  const duration =
    typeof raw.duration === 'number' && Number.isFinite(raw.duration) && raw.duration > 0
      ? raw.duration
      : null
  return { coverage: raw.coverage, duration, watched: raw.watched }
}

/**
 * Ужать список интервалов до `max`, теряя как можно меньше просмотренного.
 *
 * Порядок: короткие огрызки → склейка самых маленьких щелей (не больше 1%
 * длительности суммарно) → и только потом отбор самых длинных. Хвост при
 * равной длине выигрывает: конец ролика решает гейт.
 *
 * Пока список помещается в лимит, функция ничего не выбрасывает — иначе
 * честные доли секунды (закрытие хвоста на `ended`) пропадали бы у всех.
 */
export function capIntervals(
  intervals: readonly Interval[],
  max: number = MAX_INTERVALS,
  duration = 0,
): Interval[] {
  let merged = mergeIntervals(intervals)
  if (merged.length <= max) return merged

  merged = merged.filter(([s, e]) => e - s >= MIN_INTERVAL_SEC)
  if (merged.length <= max) return merged

  const budget = duration > 0 ? duration * GAP_BUDGET_RATIO : 0
  if (budget > 0) merged = closeSmallestGaps(merged, max, budget)
  if (merged.length <= max) return merged

  const keep = merged
    .map((iv, i) => ({ i, len: iv[1] - iv[0] }))
    .sort((a, b) => b.len - a.len || b.i - a.i)
    .slice(0, max)
    .map((x) => x.i)
    .sort((a, b) => a - b)
  return keep.map((i) => merged[i] as Interval)
}

function closeSmallestGaps(merged: Interval[], max: number, budget: number): Interval[] {
  const gaps = merged
    .slice(1)
    .map((iv, i) => ({ at: i + 1, gap: iv[0] - (merged[i] as Interval)[1] }))
    .sort((a, b) => a.gap - b.gap || a.at - b.at)
  const close = new Set<number>()
  let spent = 0
  for (const g of gaps) {
    if (merged.length - close.size <= max) break
    if (spent + g.gap > budget) break
    close.add(g.at)
    spent += g.gap
  }
  if (!close.size) return merged
  const out: Interval[] = []
  merged.forEach((iv, i) => {
    const last = out[out.length - 1]
    if (last && close.has(i)) last[1] = Math.max(last[1], iv[1])
    else out.push([iv[0], iv[1]])
  })
  return out
}
