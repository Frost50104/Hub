import type {
  ComposeEstimate,
  MediaJob,
  MediaTranscript,
  StoryboardInsert,
  StoryboardSegment,
} from '@/lib/learn'
import { formatDuration } from '@/lib/mediaJobs'
import { plural } from '@/lib/typography'

/**
 * Чистые правила вкладки «Монтаж» (0066, инкремент 7): полоса раскадровки,
 * подписи отрезков и вставок, правки раскадровки до отправки на сервер,
 * тексты оценки и хода монтажа. Цену и минуты заказа считает СЕРВЕР
 * (`POST …/compose/estimate`) — здесь только подписи к его ответу; локальная
 * таблица цен нужна лишь для «$3,00/мин» у выбора качества и «≈ $0,50» у
 * проверки сцены. Без React и сети — vitest без jsdom.
 */

export type Resolution = '540p' | '720p' | '1080p'

/** Зеркало `app/schemas/media.py::HEDRA_CENTS_PER_SEC` — только для подписей. */
export const HEDRA_CENTS_PER_SEC: Record<Resolution, number> = {
  '540p': 2.5,
  '720p': 5,
  '1080p': 6.25,
}

export const RESOLUTIONS: Resolution[] = ['540p', '720p', '1080p']

/** «$12,60», «$0,50». */
export function formatMoney(cents: number): string {
  const value = Math.max(0, cents) / 100
  return `$${value.toFixed(2).replace('.', ',')}`
}

/** «4,2 мин», «6 мин», «0,5 мин». */
export function formatMinutes(sec: number): string {
  const minutes = Math.max(0, sec) / 60
  const text = minutes.toFixed(1).replace(/\.0$/, '').replace('.', ',')
  return `${text} мин`
}

/** «$3,00/мин» для выбора качества. */
export function pricePerMinute(resolution: Resolution): string {
  return `${formatMoney(HEDRA_CENTS_PER_SEC[resolution] * 60)}/мин`
}

/** Цена проверки сцены на 10 секундах при выбранном качестве. */
export function sceneTestCostCents(resolution: Resolution): number {
  return Math.ceil(HEDRA_CENTS_PER_SEC[resolution] * 10)
}

// ─── Полоса ──────────────────────────────────────────────────────────────────

export type BarTone = 'goose' | 'keep' | 'screen' | 'insert'

export interface Bar {
  /** Проценты от ширины полосы. */
  left: number
  width: number
  tone: BarTone
  s: number
  e: number
}

function pct(t: number, duration: number): number {
  if (!duration || duration <= 0) return 0
  return Math.max(0, Math.min(100, (t / duration) * 100))
}

export function segmentBars(segments: StoryboardSegment[], duration: number | null): Bar[] {
  const d = duration ?? 0
  return segments.map((seg) => ({
    left: pct(seg.s, d),
    width: Math.max(0, pct(seg.e, d) - pct(seg.s, d)),
    tone: seg.kind === 'screen' ? 'screen' : (seg.mode ?? 'goose') === 'goose' ? 'goose' : 'keep',
    s: seg.s,
    e: seg.e,
  }))
}

export function insertBars(inserts: StoryboardInsert[], duration: number | null): Bar[] {
  const d = duration ?? 0
  return inserts.map((ins) => {
    const e = insertEnd(ins, d)
    return {
      left: pct(ins.at, d),
      width: Math.max(0, pct(e, d) - pct(ins.at, d)),
      tone: 'insert' as const,
      s: ins.at,
      e,
    }
  })
}

// ─── Отрезки ─────────────────────────────────────────────────────────────────

/** «0:00 – 1:12». */
export function formatRange(s: number, e: number): string {
  return `${formatDuration(s)} – ${formatDuration(e)}`
}

export function segmentTitle(seg: StoryboardSegment): string {
  return seg.kind === 'speaker' ? 'спикер в кадре' : 'показ экрана'
}

export interface SegmentsSummary {
  count: number
  seconds: number
}

/** Отрезки со спикером (любой режим) — для шапки «нашли лицо на N отрезках». */
export function speakerSummary(segments: StoryboardSegment[]): SegmentsSummary {
  const speaker = segments.filter((s) => s.kind === 'speaker')
  return {
    count: speaker.length,
    seconds: speaker.reduce((acc, s) => acc + Math.max(0, s.e - s.s), 0),
  }
}

/** Отрезки, где рисует гусь (режим `goose`), БЕЗ вычета вставок — вычет и
 *  минуты к оплате считает сервер в оценке. */
export function gooseSummary(segments: StoryboardSegment[]): SegmentsSummary {
  const goose = segments.filter((s) => s.kind === 'speaker' && (s.mode ?? 'goose') === 'goose')
  return {
    count: goose.length,
    seconds: goose.reduce((acc, s) => acc + Math.max(0, s.e - s.s), 0),
  }
}

/** «нашли лицо в кадре на 3 отрезках · 4:12 из 13:08». */
export function speakerHeadline(segments: StoryboardSegment[], duration: number | null): string {
  const sum = speakerSummary(segments)
  if (sum.count === 0) return 'лицо в кадре не нашли — весь ролик считается показом экрана'
  return `нашли лицо в кадре на ${plural(sum.count, 'отрезке', 'отрезках', 'отрезках')} · ${formatDuration(sum.seconds)} из ${formatDuration(duration)}`
}

/** Подпись отрезка из транскрипта: первые слова реплик, попавших в отрезок. */
export function segmentCaption(
  seg: { s: number; e: number },
  transcript: Pick<MediaTranscript, 'segments'> | undefined,
  maxChars = 90,
): string | null {
  if (!transcript) return null
  const words: string[] = []
  for (const t of transcript.segments) {
    if (t.e <= seg.s || t.s >= seg.e) continue
    words.push(...t.t.split(/\s+/).filter(Boolean))
    if (words.join(' ').length >= maxChars) break
  }
  if (!words.length) return null
  let text = ''
  for (const w of words) {
    if (text && text.length + 1 + w.length > maxChars) return `${text}…`
    text = text ? `${text} ${w}` : w
  }
  return text
}

export function setSegmentMode(
  segments: StoryboardSegment[],
  index: number,
  mode: 'goose' | 'keep',
): StoryboardSegment[] {
  return segments.map((s, i) => (i === index && s.kind === 'speaker' ? { ...s, mode } : s))
}

/** Сдвиг границы между отрезками `index` и `index+1`: оба остаются не короче
 *  `minLen`. → новая раскадровка или текст ошибки. */
export function moveBoundary(
  segments: StoryboardSegment[],
  index: number,
  newEnd: number,
  minLen = 1,
): StoryboardSegment[] | string {
  const cur = segments[index]
  const next = segments[index + 1]
  if (!cur || !next) return 'Это последняя граница — конец видео двигать нельзя'
  if (!Number.isFinite(newEnd)) return 'Время — в виде м:сс или ч:мм:сс'
  if (newEnd < cur.s + minLen) return `Отрезок ${formatRange(cur.s, cur.e)} станет короче ${minLen} с`
  if (newEnd > next.e - minLen)
    return `Отрезок ${formatRange(next.s, next.e)} станет короче ${minLen} с`
  const end = Math.round(newEnd * 100) / 100
  return segments.map((s, i) =>
    i === index ? { ...s, e: end } : i === index + 1 ? { ...s, s: end } : s,
  )
}

// ─── Вставки ─────────────────────────────────────────────────────────────────

export function insertEnd(ins: StoryboardInsert, duration: number): number {
  return Math.min(duration, ins.at + ins.duration)
}

/** «с 3:20 по 3:38». */
export function insertRange(ins: StoryboardInsert, duration: number): string {
  return `с ${formatDuration(ins.at)} по ${formatDuration(insertEnd(ins, duration))}`
}

export function sortInserts(inserts: StoryboardInsert[]): StoryboardInsert[] {
  return [...inserts].sort((a, b) => a.at - b.at)
}

/** Зеркало серверного `validate_inserts`: внутри видео, без пересечений.
 *  → текст проблемы для строки `index` или null. */
export function insertProblem(
  inserts: StoryboardInsert[],
  index: number,
  duration: number,
): string | null {
  const ins = inserts[index]
  if (!ins) return null
  if (!Number.isFinite(ins.at)) return 'Время — в виде м:сс или ч:мм:сс'
  if (ins.at < 0 || ins.at >= duration - 0.01) return 'Начало вставки за концом видео'
  const end = insertEnd(ins, duration)
  for (let i = 0; i < inserts.length; i += 1) {
    if (i === index) continue
    const other = inserts[i]!
    const otherEnd = insertEnd(other, duration)
    if (ins.at < otherEnd - 0.01 && other.at < end - 0.01) {
      return `Пересекается со вставкой ${insertRange(other, duration)}`
    }
  }
  return null
}

export function insertsSummary(inserts: StoryboardInsert[], duration: number): SegmentsSummary {
  return {
    count: inserts.length,
    seconds: inserts.reduce((acc, i) => acc + Math.max(0, insertEnd(i, duration) - i.at), 0),
  }
}

// ─── Оценка ──────────────────────────────────────────────────────────────────

const MONTH_GENITIVE = [
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря',
]

/** «из лимита октября» — месяц в родительном падеже. */
export function monthGenitive(date = new Date()): string {
  return MONTH_GENITIVE[date.getMonth()] ?? ''
}

/** «≈ 4,2 мин · ≈ $12,60» или «Без гуся · бесплатно». */
export function estimateHeadline(est: ComposeEstimate): string {
  if (!est.goose_enabled || est.chunks === 0) return 'Без гуся · бесплатно'
  return `≈ ${formatMinutes(est.billed_seconds)} · ≈ ${formatMoney(est.cost_cents)}`
}

/** Вторая строка оценки: остаток лимита или почему нельзя. */
export function estimateDetail(est: ComposeEstimate, month = monthGenitive()): string {
  if (!est.goose_enabled || est.chunks === 0) {
    return est.inserts > 0
      ? `${plural(est.inserts, 'вставка', 'вставки', 'вставок')} поверх голоса, Hedra не нужна.`
      : 'Ни отрезков гуся, ни вставок — монтировать нечего.'
  }
  const left = Math.max(0, est.monthly_cap_sec - est.monthly_used_sec - est.billed_seconds)
  if (!est.allowed && est.reason) return est.reason
  return `${est.resolution}, ${plural(est.chunks, 'отрезок', 'отрезка', 'отрезков')} со спикером без вставок. Из лимита ${month} останется ${formatMinutes(left)} из ${formatMinutes(est.monthly_cap_sec)}.`
}

/** Доля лимита месяца после этого заказа, 0–100 (для `MeterRow`). */
export function capPct(est: ComposeEstimate): number {
  if (est.monthly_cap_sec <= 0) return 100
  return Math.min(100, ((est.monthly_used_sec + est.billed_seconds) / est.monthly_cap_sec) * 100)
}

/** «22 + 4 из 60 мин». */
export function capLabel(est: ComposeEstimate): string {
  const used = Math.round(est.monthly_used_sec / 60)
  const need = est.billed_seconds / 60
  const needText = need > 0 ? ` + ${formatMinutes(est.billed_seconds).replace(' мин', '')}` : ''
  return `${used}${needText} из ${Math.round(est.monthly_cap_sec / 60)} мин`
}

/** Текст подтверждения оплаты (макет AvatarPayConfirm). */
export function payConfirmText(est: ComposeEstimate, month = monthGenitive()): string {
  const left = Math.max(0, est.monthly_cap_sec - est.monthly_used_sec - est.billed_seconds)
  return (
    `Hedra спишет деньги с кошелька по факту: ${formatMinutes(est.billed_seconds)} гуся в ${est.resolution}, ` +
    `${plural(est.chunks, 'отрезок', 'отрезка', 'отрезков')} там, где в кадре был спикер. ` +
    `Из лимита ${month} зарезервируем ${formatMinutes(est.billed_seconds)} — останется ${formatMinutes(left)} из ${formatMinutes(est.monthly_cap_sec)}. ` +
    'Отменить после старта можно, но уже оплаченные отрезки не вернутся. Если Hedra отклонит материал, минуты лимита вернутся сами.'
  )
}

// ─── Ход и итог монтажа ──────────────────────────────────────────────────────

export interface ComposeProgress {
  pct: number | null
  text: string
}

interface HedraChunkRow {
  status?: string
}

/** Подпись хода монтажа по `result.progress` и `result.hedra.chunks`. */
export function composeProgress(job: MediaJob | null): ComposeProgress {
  const progress = job?.result.progress as { stage?: string; pct?: number } | undefined
  const pct = typeof progress?.pct === 'number' ? progress.pct : null
  const stage = progress?.stage ?? ''
  const hedra = job?.result.hedra as { chunks?: HedraChunkRow[] } | undefined
  const chunks = hedra?.chunks ?? []
  const done = chunks.filter((c) => c.status === 'downloaded').length
  if (job?.status === 'queued') return { pct, text: 'ждём очереди' }
  const goose = /^goose (\d+)\/(\d+)/.exec(stage)
  if (goose) {
    return {
      pct,
      text: `гусь ${goose[1]} из ${goose[2]} · Hedra рендерит${done ? ` · готово ${done}` : ''}`,
    }
  }
  const voice = /^voice (\d+)\/(\d+)/.exec(stage)
  if (voice) return { pct, text: `голос для отрезка ${voice[1]} из ${voice[2]}` }
  if (stage === 'render') return { pct, text: 'склейка видео' }
  if (stage === 'probe') return { pct, text: 'готовим чистовик' }
  return { pct, text: pct != null ? `${pct} %` : 'запуск' }
}

export interface ComposeSummary {
  gooseEnabled: boolean
  gooseChunks: number
  gooseSeconds: number
  inserts: number
  insertSeconds: number
  costCents: number
  billedSeconds: number
  resolution: string | null
}

/** Итог монтажа из `params` (снимок заказа) и `result` задания. */
export function composeSummary(job: MediaJob | null, duration: number): ComposeSummary | null {
  if (!job) return null
  const plan = job.result.plan as
    | { goose_seconds?: number; chunks?: number; inserts?: number; resolution?: string }
    | undefined
  const params = job.params as {
    goose_enabled?: boolean
    chunks?: [number, number][]
    inserts?: StoryboardInsert[]
    resolution?: string
  }
  const inserts = Array.isArray(params.inserts) ? params.inserts : []
  const chunks = Array.isArray(params.chunks) ? params.chunks : []
  return {
    gooseEnabled: params.goose_enabled ?? chunks.length > 0,
    gooseChunks: plan?.chunks ?? chunks.length,
    gooseSeconds:
      plan?.goose_seconds ?? chunks.reduce((acc, [s, e]) => acc + Math.max(0, e - s), 0),
    inserts: inserts.length,
    insertSeconds: insertsSummary(inserts, duration).seconds,
    costCents: typeof job.result.cost_cents === 'number' ? job.result.cost_cents : 0,
    billedSeconds: typeof job.result.billed_seconds === 'number' ? job.result.billed_seconds : 0,
    resolution: plan?.resolution ?? params.resolution ?? null,
  }
}

/** Полоса под плеером результата: отрезки гуся и вставки из снимка заказа. */
export function composeBars(job: MediaJob | null, duration: number): Bar[] {
  if (!job) return []
  const params = job.params as { chunks?: [number, number][]; inserts?: StoryboardInsert[] }
  const chunks = Array.isArray(params.chunks) ? params.chunks : []
  const goose: Bar[] = chunks.map(([s, e]) => ({
    left: pct(s, duration),
    width: Math.max(0, pct(e, duration) - pct(s, duration)),
    tone: 'goose' as const,
    s,
    e,
  }))
  return [...goose, ...insertBars(Array.isArray(params.inserts) ? params.inserts : [], duration)]
}
