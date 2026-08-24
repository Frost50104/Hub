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

/** Щель короче — считаем одним куском. Та же, что на сервере. */
export const GAP_CLOSE = 0.5

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

/** Ответ ручки прогресса: серверное покрытие и длительность из файла. */
export interface VideoProgressEcho {
  coverage: number
  duration: number | null
  watched: boolean
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
