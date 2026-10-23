import type { DerivedMedia, MediaDetail, MediaJob, MediaJobKind, MediaJobStatus } from '@/lib/learn'
import { plural } from '@/lib/typography'

/**
 * Чистые правила экрана конвейера видео (0066): какое состояние показать на
 * блоке, когда опрашивать сервер, как подписать ход работы. Без React и
 * сети — под vitest без jsdom.
 */

export const ACTIVE_JOB_STATUSES: readonly MediaJobStatus[] = ['queued', 'running']

export function isActiveJob(job: MediaJob): boolean {
  return ACTIVE_JOB_STATUSES.includes(job.status)
}

/** Самое свежее задание вида (список сервера — свежие первыми). */
export function latestJob(detail: MediaDetail | undefined, kind: MediaJobKind): MediaJob | null {
  if (!detail) return null
  return detail.jobs.find((j) => j.kind === kind) ?? null
}

export function activeJob(detail: MediaDetail | undefined, kind?: MediaJobKind): MediaJob | null {
  if (!detail) return null
  return detail.jobs.find((j) => isActiveJob(j) && (kind === undefined || j.kind === kind)) ?? null
}

/** Идёт ли по файлу хоть какая-то работа — от этого зависит опрос. */
export function hasActiveWork(detail: MediaDetail | undefined): boolean {
  if (!detail) return false
  return detail.status === 'processing' || detail.jobs.some(isActiveJob)
}

/** Интервал опроса `GET /learn/media/{id}`: конвертация и расшифровка —
 *  5 с, гусь — 15 с (Hedra отвечает минутами), ничего не идёт — не опрашиваем. */
export function pollIntervalMs(detail: MediaDetail | undefined): number | false {
  if (!hasActiveWork(detail)) return false
  const job = activeJob(detail)
  if (job && (job.kind === 'compose' || job.kind === 'avatar_test')) return 15_000
  return 5_000
}

export type TranscribeState = 'unavailable' | 'none' | 'running' | 'ready' | 'failed'

/** Состояние вкладки «Субтитры» (макет SubtitlesTab: четыре состояния +
 *  «идёт»). Готовый транскрипт важнее старой ошибки; активное задание важнее
 *  всего. */
export function transcribeState(detail: MediaDetail | undefined): TranscribeState {
  if (!detail) return 'none'
  if (activeJob(detail, 'transcribe')) return 'running'
  if (detail.transcript) return 'ready'
  // Монтаж своего транскрипта не имеет — дорожку чистовика сервер отдаёт по
  // цепочке `source_media_id` (`subtitle_url`), и для человека это «есть».
  if (detail.variant === 'composed' && detail.subtitle_url) return 'ready'
  const last = latestJob(detail, 'transcribe')
  if (last?.status === 'failed') return 'failed'
  if (!detail.capabilities.transcribe && detail.status === 'ready') return 'unavailable'
  return 'none'
}

export type BlockStatus =
  | { kind: 'processing'; label: string; pct: number | null }
  | { kind: 'failed'; label: string }
  | { kind: 'ready' }

/** Состояние самого файла на блоке редактора (макет Main, состояния 4 и 6). */
export function blockStatus(detail: MediaDetail | undefined): BlockStatus {
  if (!detail) return { kind: 'ready' }
  if (detail.status === 'processing') {
    const job = activeJob(detail, 'merge') ?? activeJob(detail, 'normalize')
    const pct = job?.result.progress?.pct ?? null
    const label = job?.kind === 'merge' ? 'Собираем из записей…' : 'Конвертируем в MP4…'
    return {
      kind: 'processing',
      label,
      pct: typeof pct === 'number' ? pct : null,
    }
  }
  if (detail.status === 'failed') {
    const job = latestJob(detail, 'merge') ?? latestJob(detail, 'normalize')
    return {
      kind: 'failed',
      label: job?.kind === 'merge' ? 'Сборка не удалась' : 'Конвертация не удалась',
    }
  }
  return { kind: 'ready' }
}

/** Чип расшифровки под блоком: «Субтитров нет» · «Расшифровка… N %» ·
 *  «Субтитры» · «Расшифровка не удалась». */
export function transcribeChip(detail: MediaDetail | undefined): {
  text: string
  tone: 'neutral' | 'progress' | 'ok' | 'danger'
} | null {
  if (!detail || detail.kind !== 'video' || detail.status !== 'ready') return null
  const state = transcribeState(detail)
  if (state === 'running') {
    const pct = activeJob(detail, 'transcribe')?.result.progress?.pct
    return {
      text: typeof pct === 'number' && pct > 0 ? `Расшифровка… ${pct} %` : 'Расшифровка…',
      tone: 'progress',
    }
  }
  if (state === 'ready') return { text: 'Субтитры', tone: 'ok' }
  if (state === 'failed') return { text: 'Расшифровка не удалась', tone: 'danger' }
  if (state === 'unavailable') return null
  return { text: 'Субтитров нет', tone: 'neutral' }
}

/** Человеческая причина провала из `error` задания («код: текст»). */
export function failureText(job: MediaJob | null): string {
  const raw = (job?.error ?? '').trim()
  if (!raw) return 'Причина не записана'
  const [code, ...rest] = raw.split(':')
  const detail = rest.join(':').trim()
  const known: Record<string, string> = {
    stt_not_configured: 'Расшифровка не настроена на сервере',
    stt_no_segments_route: 'Служба распознавания ещё не обновлена',
    stt_unreachable: 'Служба распознавания не отвечает',
    stt_busy: 'Служба распознавания занята дольше обычного',
    no_space: 'На сервере мало места',
    no_audio_stream: 'В видео нет звуковой дорожки',
    no_video_stream: 'В файле нет видеодорожки',
    source_missing: 'Исходный файл не найден на сервере',
    cancelled: 'Отменено',
    lease_expired: 'Воркер не ответил вовремя',
    worker_stopped: 'Сервер перезапускался — задание вернётся в очередь',
    avatar_disabled: 'Гусь выключен на сервере',
    scene_missing: 'Сцена гуся не задана или не готова',
    insufficient_balance: 'На кошельке Hedra нет денег — пополните баланс',
    moderation_failed: 'Hedra отклонила материал модерацией',
    hedra_auth: 'Ключ Hedra не принят — сообщите администратору',
    invalid_argument: 'Hedra не приняла запрос',
    hedra_no_output: 'Hedra не отдала результат',
    hedra_timeout: 'Hedra не ответила вовремя',
    nothing_to_compose: 'Ни отрезков гуся, ни вставок — монтировать нечего',
    insert_missing: 'Вставка не готова или удалена',
    faststart_missing: 'Файл собрался без быстрого старта',
  }
  const text = known[(code ?? '').trim()]
  if (text) return text
  return detail || raw
}

/** Проверка файла до загрузки: расширение и тип. При выключенном конвейере —
 *  только MP4; `octet-stream` от десктопных браузеров решается расширением. */
export function videoFileProblem(
  file: { name: string; type: string; size: number },
  pipelineOn: boolean,
  maxBytes: number,
): string | null {
  const ext = (file.name.split('.').pop() ?? '').toLowerCase()
  const allowed = pipelineOn ? ['mp4', 'mov', 'webm', 'm4v'] : ['mp4']
  const typeOk =
    file.type === '' || file.type === 'application/octet-stream' || file.type.startsWith('video/')
  if (!allowed.includes(ext) || !typeOk) {
    return pipelineOn ? 'Видео — MP4, MOV или WebM' : 'Только MP4 (H.264) с faststart'
  }
  if (file.size > maxBytes) {
    return `Файл больше лимита ${Math.round(maxBytes / (1024 * 1024))} МБ`
  }
  return null
}

/** «3:51», «27:08», «1:02:03». */
export function formatDuration(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return '—'
  const total = Math.round(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const mm = h ? String(m).padStart(2, '0') : String(m)
  return `${h ? `${h}:` : ''}${mm}:${String(s).padStart(2, '0')}`
}

/** «184 МБ», «3,2 ГБ». */
export function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1).replace('.', ',')} ГБ`
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} МБ`
  return `${Math.max(1, Math.round(bytes / 1024))} КБ`
}

export type CleanupState = 'none' | 'running' | 'ready' | 'failed'

/** Свежий готовый чистовик этого файла (производные — старые первыми). */
export function latestCleaned(detail: MediaDetail | undefined): DerivedMedia | null {
  if (!detail) return null
  const ready = detail.derived.filter((d) => d.variant === 'cleaned' && d.status === 'ready')
  return ready.length ? ready[ready.length - 1]! : null
}

/** Состояние вкладки «Чистовик»: идёт → есть готовый → последняя попытка
 *  провалилась → ещё нет. Готовый чистовик важнее старой ошибки. */
export function cleanupState(detail: MediaDetail | undefined): CleanupState {
  if (!detail) return 'none'
  if (activeJob(detail, 'cleanup')) return 'running'
  if (latestCleaned(detail)) return 'ready'
  if (latestJob(detail, 'cleanup')?.status === 'failed') return 'failed'
  return 'none'
}

/** Задание `cleanup`, породившее этот чистовик (по `output_media_id` нет —
 *  берём последнее завершённое). */
export function cleanupJobFor(detail: MediaDetail | undefined): MediaJob | null {
  if (!detail) return null
  return detail.jobs.find((j) => j.kind === 'cleanup' && j.status === 'done') ?? null
}

export type ComposeState = 'none' | 'running' | 'ready' | 'failed'

/** Свежий готовый монтаж — производная ЧИСТОВИКА (`source_media_id` у
 *  монтажа указывает на чистовик, поэтому в `derived` оригинала его нет). */
export function latestComposed(detail: MediaDetail | undefined): DerivedMedia | null {
  if (!detail) return null
  const ready = detail.derived.filter((d) => d.variant === 'composed' && d.status === 'ready')
  return ready.length ? ready[ready.length - 1]! : null
}

/** Состояние вкладки «Монтаж» по детали чистовика: идёт → есть готовый →
 *  провал → ещё нет. */
export function composeState(detail: MediaDetail | undefined): ComposeState {
  if (!detail) return 'none'
  if (activeJob(detail, 'compose')) return 'running'
  if (latestComposed(detail)) return 'ready'
  if (latestJob(detail, 'compose')?.status === 'failed') return 'failed'
  return 'none'
}

export function composeJobFor(detail: MediaDetail | undefined): MediaJob | null {
  if (!detail) return null
  return detail.jobs.find((j) => j.kind === 'compose' && j.status === 'done') ?? null
}

export type AnalyzeState = 'none' | 'running' | 'failed' | 'ready'

/** Раскадровка: `analyze` ставится сам после чистовика; «ready» решает
 *  наличие строки на сервере (`GET …/storyboard`), здесь — только ход. */
export function analyzeState(detail: MediaDetail | undefined, hasBoard: boolean): AnalyzeState {
  if (hasBoard) return 'ready'
  if (!detail) return 'none'
  if (activeJob(detail, 'analyze')) return 'running'
  if (latestJob(detail, 'analyze')?.status === 'failed') return 'failed'
  return 'none'
}

export interface CleanupStats {
  source_sec: number
  output_sec: number
  removed_sec: number
  pauses: number
}

export function cleanupStats(job: MediaJob | null): CleanupStats | null {
  const raw = job?.result.stats as Partial<CleanupStats> | undefined
  if (!raw || typeof raw.source_sec !== 'number') return null
  return {
    source_sec: raw.source_sec,
    output_sec: raw.output_sec ?? raw.source_sec,
    removed_sec: raw.removed_sec ?? 0,
    pauses: raw.pauses ?? 0,
  }
}

export interface PauseRow {
  at: number
  source_at: number
  was_sec: number
  now_sec: number
  context: string | null
}

export function cleanupPauses(job: MediaJob | null): PauseRow[] {
  const raw = job?.result.pauses
  return Array.isArray(raw) ? (raw as PauseRow[]) : []
}

/** «−1 мин 12 с», «−48 с». */
export function formatDelta(sec: number): string {
  const total = Math.round(Math.abs(sec))
  const m = Math.floor(total / 60)
  const s = total % 60
  const sign = sec < 0 ? '−' : ''
  if (m === 0) return `${sign}${s} с`
  return `${sign}${m} мин${s ? ` ${s} с` : ''}`
}

/** Время в оригинале → время в чистовике по списку ужатых пауз (монотонно). */
export function mapOriginalTime(t: number, pauses: PauseRow[]): number {
  let shift = 0
  for (const p of pauses) {
    if (p.source_at >= t) break
    const cut = Math.max(0, p.was_sec - p.now_sec)
    if (t < p.source_at + p.was_sec) {
      // Внутри паузы: пропорционально ужатию.
      const inside = t - p.source_at
      return Math.max(0, t - shift - Math.min(cut, Math.max(0, inside - p.now_sec / 2)))
    }
    shift += cut
  }
  return Math.max(0, t - shift)
}

/** Текст подтверждения замены в опубликованном уроке (макет SwapConfirm). */
export function swapImpactText(
  inProgress: number,
  otherLessons: number,
  shorterBy: number | null,
): string {
  const head =
    shorterBy != null && shorterBy > 1
      ? `Чистовик короче оригинала на ${formatDelta(shorterBy)}. `
      : ''
  const people =
    inProgress > 0
      ? `Сейчас урок проходят ${plural(inProgress, 'сотрудник', 'сотрудника', 'сотрудников')} — их прогресс просмотра этого видео сбросится, ролик придётся посмотреть заново. У тех, кто уже завершил урок, ничего не изменится.`
      : 'Никто сейчас не проходит этот урок — прогресс просмотра не пострадает. У тех, кто уже завершил урок, ничего не изменится.'
  const others =
    otherLessons > 0
      ? ` Это видео стоит ещё в ${plural(otherLessons, 'уроке', 'уроках', 'уроках')} — там останется оригинал.`
      : ''
  return `${head}${people}${others} Замена вступит в силу после сохранения урока.`
}
