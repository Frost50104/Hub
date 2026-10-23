import { describe, expect, it } from 'vitest'

import type { MediaDetail, MediaJob } from './learn'
import {
  blockStatus,
  formatBytes,
  formatDuration,
  failureText,
  hasActiveWork,
  pollIntervalMs,
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
