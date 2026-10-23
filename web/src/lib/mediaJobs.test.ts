import { describe, expect, it } from 'vitest'

import type { MediaDetail, MediaJob, MediaRetake } from './learn'
import {
  blockStatus,
  cleanupPauses,
  cleanupRetakes,
  cleanupState,
  cleanupStats,
  composeState,
  analyzeState,
  defaultRetakeSelection,
  latestComposed,
  formatBytes,
  formatDelta,
  formatDuration,
  failureText,
  hasActiveWork,
  latestCleaned,
  mapOriginalTime,
  pollIntervalMs,
  retakeCuts,
  retakeKey,
  retakeReasonLabel,
  retakesSummary,
  swapImpactText,
  transcribeChip,
  transcribeState,
  videoFileProblem,
} from './mediaJobs'

const job = (over: Partial<MediaJob>): MediaJob => ({
  id: 'j',
  media_id: 'm',
  kind: 'transcribe',
  status: 'queued',
  params: {},
  result: {},
  error: null,
  attempts: 0,
  created_at: '2026-10-22T10:00:00Z',
  started_at: null,
  finished_at: null,
  ...over,
})

const detail = (over: Partial<MediaDetail>): MediaDetail => ({
  id: 'm',
  kind: 'video',
  role: 'content',
  status: 'ready',
  file_name: 'a.mp4',
  mime: 'video/mp4',
  size_bytes: 10,
  duration_sec: 231,
  url: '/api/media/m?e=1&s=x',
  variant: null,
  source_media_id: null,
  created_at: '2026-10-22T10:00:00Z',
  parts: [],
  derived: [],
  jobs: [],
  capabilities: { transcribe: true, cleanup: false, compose: false },
  transcript: null,
  subtitle_url: null,
  ...over,
})

describe('опрос', () => {
  it('идёт только при активной работе; гусь — реже', () => {
    expect(pollIntervalMs(undefined)).toBe(false)
    expect(pollIntervalMs(detail({}))).toBe(false)
    expect(pollIntervalMs(detail({ status: 'processing' }))).toBe(5_000)
    expect(pollIntervalMs(detail({ jobs: [job({ status: 'running' })] }))).toBe(5_000)
    expect(pollIntervalMs(detail({ jobs: [job({ kind: 'compose', status: 'queued' })] }))).toBe(
      15_000,
    )
    expect(hasActiveWork(detail({ jobs: [job({ status: 'done' })] }))).toBe(false)
  })
})

describe('состояние расшифровки', () => {
  it('у монтажа без своего транскрипта субтитры чистовика считаются готовыми', () => {
    expect(
      transcribeState(detail({ variant: 'composed', subtitle_url: '/api/media/s?e=1&s=x' })),
    ).toBe('ready')
    expect(transcribeState(detail({ variant: 'composed', subtitle_url: null }))).toBe('none')
    expect(transcribeChip(detail({ variant: 'composed', subtitle_url: '/api/media/s' }))?.text).toBe(
      'Субтитры',
    )
  })
  it('активное задание важнее всего, транскрипт важнее старой ошибки', () => {
    expect(transcribeState(undefined)).toBe('none')
    expect(transcribeState(detail({}))).toBe('none')
    expect(transcribeState(detail({ jobs: [job({ status: 'running' })] }))).toBe('running')
    expect(
      transcribeState(
        detail({
          transcript: { language: 'ru', chars: 10, provider: 'local', model: 'm', updated_at: 'x' },
          jobs: [job({ status: 'failed', error: 'stt_busy' })],
        }),
      ),
    ).toBe('ready')
    expect(transcribeState(detail({ jobs: [job({ status: 'failed', error: 'x' })] }))).toBe(
      'failed',
    )
    expect(
      transcribeState(
        detail({ capabilities: { transcribe: false, cleanup: false, compose: false } }),
      ),
    ).toBe('unavailable')
  })

  it('чип под блоком', () => {
    expect(transcribeChip(detail({}))).toEqual({ text: 'Субтитров нет', tone: 'neutral' })
    expect(
      transcribeChip(
        detail({ jobs: [job({ status: 'running', result: { progress: { pct: 40 } } })] }),
      ),
    ).toEqual({ text: 'Расшифровка… 40 %', tone: 'progress' })
    expect(transcribeChip(detail({ jobs: [job({ status: 'queued' })] }))).toEqual({
      text: 'Расшифровка…',
      tone: 'progress',
    })
    expect(transcribeChip(detail({ status: 'processing' }))).toBeNull()
    expect(
      transcribeChip(
        detail({ capabilities: { transcribe: false, cleanup: false, compose: false } }),
      ),
    ).toBeNull()
  })
})

describe('состояние файла на блоке', () => {
  it('конвертация и сборка с процентом, провал — с именем операции', () => {
    expect(blockStatus(detail({}))).toEqual({ kind: 'ready' })
    expect(
      blockStatus(
        detail({
          status: 'processing',
          jobs: [job({ kind: 'normalize', status: 'running', result: { progress: { pct: 38 } } })],
        }),
      ),
    ).toEqual({ kind: 'processing', label: 'Конвертируем в MP4…', pct: 38 })
    expect(
      blockStatus(
        detail({ status: 'processing', jobs: [job({ kind: 'merge', status: 'queued' })] }),
      ),
    ).toEqual({ kind: 'processing', label: 'Собираем из записей…', pct: null })
    expect(
      blockStatus(detail({ status: 'failed', jobs: [job({ kind: 'merge', status: 'failed' })] })),
    ).toEqual({ kind: 'failed', label: 'Сборка не удалась' })
  })
})

describe('тексты', () => {
  it('причина провала по коду', () => {
    expect(failureText(job({ error: 'stt_no_segments_route: {"detail":"Not Found"}' }))).toBe(
      'Служба распознавания ещё не обновлена',
    )
    expect(failureText(job({ error: 'ffmpeg: код 1' }))).toBe('код 1')
    expect(failureText(job({ error: null }))).toBe('Причина не записана')
    expect(failureText(null)).toBe('Причина не записана')
  })

  it('длительность и размер', () => {
    expect(formatDuration(231)).toBe('3:51')
    expect(formatDuration(1628)).toBe('27:08')
    expect(formatDuration(3723)).toBe('1:02:03')
    expect(formatDuration(null)).toBe('—')
    expect(formatBytes(184 * 1024 * 1024)).toBe('184 МБ')
    expect(formatBytes(3.2 * 1024 ** 3)).toBe('3,2 ГБ')
    expect(formatBytes(500)).toBe('1 КБ')
  })

  it('проверка файла до загрузки', () => {
    const mb = 1024 * 1024
    expect(
      videoFileProblem({ name: 'a.mp4', type: 'video/mp4', size: mb }, false, 300 * mb),
    ).toBeNull()
    expect(
      videoFileProblem({ name: 'a.mov', type: 'video/quicktime', size: mb }, false, 300 * mb),
    ).toBe('Только MP4 (H.264) с faststart')
    expect(videoFileProblem({ name: 'a.MOV', type: '', size: mb }, true, 300 * mb)).toBeNull()
    expect(
      videoFileProblem(
        { name: 'a.webm', type: 'application/octet-stream', size: mb },
        true,
        300 * mb,
      ),
    ).toBeNull()
    expect(
      videoFileProblem({ name: 'a.avi', type: 'video/x-msvideo', size: mb }, true, 300 * mb),
    ).toBe('Видео — MP4, MOV или WebM')
    expect(
      videoFileProblem({ name: 'a.mp4', type: 'video/mp4', size: 301 * mb }, true, 300 * mb),
    ).toBe('Файл больше лимита 300 МБ')
  })
})

describe('чистовик', () => {
  const cleaned = {
    id: 'c',
    kind: 'video' as const,
    variant: 'cleaned' as const,
    status: 'ready' as const,
    url: '/api/media/c?e=1&s=x',
    duration_sec: 788,
    size_bytes: 10,
    file_name: 'a — чистовик.mp4',
    created_at: '2026-10-22T10:00:00Z',
  }

  it('состояние вкладки и свежий чистовик', () => {
    expect(cleanupState(detail({}))).toBe('none')
    expect(cleanupState(detail({ jobs: [job({ kind: 'cleanup', status: 'running' })] }))).toBe(
      'running',
    )
    expect(
      cleanupState(
        detail({ derived: [cleaned], jobs: [job({ kind: 'cleanup', status: 'failed' })] }),
      ),
    ).toBe('ready')
    expect(cleanupState(detail({ jobs: [job({ kind: 'cleanup', status: 'failed' })] }))).toBe(
      'failed',
    )
    expect(latestCleaned(detail({ derived: [{ ...cleaned, id: 'old' }, cleaned] }))?.id).toBe('c')
    expect(latestCleaned(detail({ derived: [{ ...cleaned, status: 'processing' }] }))).toBeNull()
  })

  it('статистика и паузы из result задания', () => {
    const done = job({
      kind: 'cleanup',
      status: 'done',
      result: {
        stats: { source_sec: 860, output_sec: 788, removed_sec: 72, pauses: 37 },
        pauses: [
          { at: 41, source_at: 41, was_sec: 3.1, now_sec: 0.7, context: 'после «добрый день»' },
        ],
      },
    })
    expect(cleanupStats(done)).toEqual({
      source_sec: 860,
      output_sec: 788,
      removed_sec: 72,
      pauses: 37,
      retakes: 0,
      retakes_sec: 0,
    })
    expect(cleanupStats(job({}))).toBeNull()
    expect(cleanupPauses(done)).toHaveLength(1)
    expect(cleanupPauses(null)).toEqual([])
  })

  it('перезаписи: выбор по умолчанию, итог, тело заказа и отчёт', () => {
    const marker: MediaRetake = {
      s: 25.42,
      e: 32.37,
      reason: 'marker',
      confidence: 'high',
      marker: 'Стоп.',
      before: 'Важно, весь офис Стоп.',
      after: 'Важно, весь офис компании',
    }
    const weak: MediaRetake = {
      s: 100,
      e: 104.5,
      reason: 'repeat',
      confidence: 'low',
      marker: null,
      before: 'выбираем учётную запись,',
      after: 'выбираем профиль и связь',
    }
    const strong: MediaRetake = { ...weak, s: 200, e: 206, confidence: 'high' }
    const items = [marker, weak, strong]
    expect(retakeKey(marker)).toBe('25.42-32.37')
    const def = defaultRetakeSelection(items)
    expect([...def]).toEqual([retakeKey(marker), retakeKey(strong)])
    const sum = retakesSummary(items, def)
    expect(sum.count).toBe(2)
    expect(sum.seconds).toBeCloseTo(12.95, 5)
    expect(retakeReasonLabel(marker)).toBe('метка «Стоп.»')
    expect(retakeReasonLabel({ ...marker, marker: null })).toBe('голосовая метка')
    expect(retakeReasonLabel(weak)).toBe('похоже на повтор')
    expect(retakeReasonLabel(strong)).toBe('повтор начала фразы')
    // Тело заказа — только выбранные; без кандидатов поле не шлём (сервер решит сам).
    expect(retakeCuts(items, def)).toEqual([
      { s: 25.42, e: 32.37 },
      { s: 200, e: 206 },
    ])
    expect(retakeCuts(items, new Set())).toEqual([])
    expect(retakeCuts(undefined, def)).toBeUndefined()
    const done = job({
      kind: 'cleanup',
      status: 'done',
      result: { retakes: [{ ...marker, applied: true }, { ...weak, applied: false }] },
    })
    expect(cleanupRetakes(done).filter((r) => r.applied)).toHaveLength(1)
    expect(cleanupRetakes(null)).toEqual([])
  })

  it('дельта, перенос времени и текст подтверждения', () => {
    expect(formatDelta(-72)).toBe('−1 мин 12 с')
    expect(formatDelta(48)).toBe('48 с')
    expect(formatDelta(-120)).toBe('−2 мин')
    const pauses = [
      { at: 10, source_at: 10, was_sec: 4, now_sec: 0.7, context: null },
      { at: 26.7, source_at: 30, was_sec: 2, now_sec: 0.7, context: null },
    ]
    expect(mapOriginalTime(5, pauses)).toBe(5)
    expect(mapOriginalTime(20, pauses)).toBeCloseTo(16.7, 5)
    expect(mapOriginalTime(40, pauses)).toBeCloseTo(35.4, 5)
    const t = mapOriginalTime(12, pauses)
    expect(t).toBeGreaterThanOrEqual(10)
    expect(t).toBeLessThanOrEqual(12)
    expect(swapImpactText(14, 2, 72)).toContain('14\u00a0сотрудников')
    expect(swapImpactText(14, 2, 72)).toContain('Чистовик короче оригинала на 1 мин 12 с')
    expect(swapImpactText(14, 2, 72)).toContain('ещё в 2\u00a0уроках')
    expect(swapImpactText(0, 0, null)).toContain('Никто сейчас не проходит')
    expect(swapImpactText(1, 0, 0.5)).toContain('1\u00a0сотрудник —')
  })
})

describe('состояние монтажа', () => {
  const composed = {
    id: 'c1',
    kind: 'video' as const,
    variant: 'composed' as const,
    status: 'ready' as const,
    url: '/api/media/c1',
    duration_sec: 230,
    size_bytes: 1,
    file_name: 'a — монтаж.mp4',
    created_at: '2026-10-23T10:00:00Z',
  }
  it('идёт → готов → провал → нет', () => {
    expect(composeState(undefined)).toBe('none')
    expect(composeState(detail({ jobs: [job({ kind: 'compose', status: 'running' })] }))).toBe(
      'running',
    )
    expect(
      composeState(detail({ derived: [composed], jobs: [job({ kind: 'compose', status: 'failed' })] })),
    ).toBe('ready')
    expect(latestComposed(detail({ derived: [composed] }))?.id).toBe('c1')
    expect(composeState(detail({ jobs: [job({ kind: 'compose', status: 'failed' })] }))).toBe('failed')
    expect(composeState(detail({}))).toBe('none')
  })
  it('раскадровка: строка на сервере важнее хода задания', () => {
    expect(analyzeState(undefined, true)).toBe('ready')
    expect(analyzeState(detail({ jobs: [job({ kind: 'analyze', status: 'queued' })] }), false)).toBe(
      'running',
    )
    expect(analyzeState(detail({ jobs: [job({ kind: 'analyze', status: 'failed' })] }), false)).toBe(
      'failed',
    )
    expect(analyzeState(detail({}), false)).toBe('none')
  })
  it('коды Hedra переводятся', () => {
    expect(failureText(job({ error: 'insufficient_balance: 402' }))).toContain('Hedra')
    expect(failureText(job({ error: 'moderation_failed: x' }))).toContain('модерацией')
  })
})
