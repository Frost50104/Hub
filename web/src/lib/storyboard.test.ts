import { describe, expect, it } from 'vitest'

const NB = '\u00a0'

import type { ComposeEstimate, MediaJob, StoryboardInsert, StoryboardSegment } from './learn'
import {
  capLabel,
  capPct,
  composeBars,
  composeProgress,
  composeSummary,
  estimateDetail,
  estimateHeadline,
  formatMinutes,
  formatMoney,
  gooseSummary,
  insertBars,
  insertProblem,
  insertRange,
  moveBoundary,
  payConfirmText,
  pricePerMinute,
  sceneTestCostCents,
  segmentBars,
  segmentCaption,
  setSegmentMode,
  speakerHeadline,
} from './storyboard'

const segments: StoryboardSegment[] = [
  { s: 0, e: 72, kind: 'speaker', mode: 'goose' },
  { s: 72, e: 400, kind: 'screen' },
  { s: 400, e: 485, kind: 'speaker', mode: 'keep' },
  { s: 485, e: 788, kind: 'screen' },
]

const estimate = (over: Partial<ComposeEstimate>): ComposeEstimate => ({
  goose_enabled: true,
  resolution: '720p',
  goose_seconds: 252,
  segments: 4,
  inserts: 0,
  chunks: 3,
  billed_seconds: 252,
  cost_cents: 1260,
  currency: 'USD',
  monthly_cap_sec: 3600,
  monthly_used_sec: 1320,
  allowed: true,
  reason: null,
  scene_set: true,
  hedra_estimate: null,
  ...over,
})

describe('деньги и минуты', () => {
  it('форматирует с запятой', () => {
    expect(formatMoney(1260)).toBe('$12,60')
    expect(formatMoney(50)).toBe('$0,50')
    expect(formatMinutes(252)).toBe('4,2 мин')
    expect(formatMinutes(360)).toBe('6 мин')
    expect(pricePerMinute('720p')).toBe('$3,00/мин')
    expect(pricePerMinute('540p')).toBe('$1,50/мин')
    expect(sceneTestCostCents('720p')).toBe(50)
    expect(sceneTestCostCents('540p')).toBe(25)
  })
})

describe('полоса раскадровки', () => {
  it('отрезки в процентах с тоном по виду и режиму', () => {
    const bars = segmentBars(segments, 788)
    expect(bars.map((b) => b.tone)).toEqual(['goose', 'screen', 'keep', 'screen'])
    expect(bars[0]!.left).toBe(0)
    expect(bars[0]!.width).toBeCloseTo((72 / 788) * 100, 3)
    expect(segmentBars(segments, null)).toHaveLength(4)
  })
  it('вставки клампятся по концу видео', () => {
    const bars = insertBars([{ media_id: 'i', at: 780, duration: 30 }], 788)
    expect(bars[0]!.e).toBe(788)
    expect(bars[0]!.width).toBeCloseTo((8 / 788) * 100, 3)
  })
})

describe('отрезки', () => {
  it('шапка считает только спикера, гусь — только режим goose', () => {
    expect(speakerHeadline(segments, 788)).toBe(`нашли лицо в кадре на 2${NB}отрезках · 2:37 из 13:08`)
    expect(gooseSummary(segments)).toEqual({ count: 1, seconds: 72 })
    expect(speakerHeadline([{ s: 0, e: 10, kind: 'screen' }], 10)).toContain('не нашли')
  })
  it('подпись — слова транскрипта внутри отрезка, обрезка по словам', () => {
    const transcript = {
      segments: [
        { s: 0, e: 5, t: 'Приветствую вас дорогие коллеги' },
        { s: 5, e: 80, t: 'сегодня разберём как создать задачу' },
        { s: 90, e: 100, t: 'не сюда' },
      ],
    }
    expect(segmentCaption({ s: 0, e: 72 }, transcript, 30)).toBe('Приветствую вас дорогие…')
    expect(segmentCaption({ s: 0, e: 72 }, transcript)).toBe(
      'Приветствую вас дорогие коллеги сегодня разберём как создать задачу',
    )
    expect(segmentCaption({ s: 100, e: 120 }, transcript)).toBeNull()
    expect(segmentCaption({ s: 0, e: 1 }, undefined)).toBeNull()
  })
  it('режим меняется только у спикера', () => {
    expect(setSegmentMode(segments, 0, 'keep')[0]!.mode).toBe('keep')
    expect(setSegmentMode(segments, 1, 'keep')[1]!.mode).toBeUndefined()
  })
  it('границу двигают внутри соседей, последнюю — нельзя', () => {
    const moved = moveBoundary(segments, 0, 60)
    expect(Array.isArray(moved)).toBe(true)
    if (Array.isArray(moved)) {
      expect(moved[0]!.e).toBe(60)
      expect(moved[1]!.s).toBe(60)
    }
    expect(typeof moveBoundary(segments, 0, 0.5)).toBe('string')
    expect(typeof moveBoundary(segments, 0, 399.8)).toBe('string')
    expect(typeof moveBoundary(segments, 3, 700)).toBe('string')
    expect(typeof moveBoundary(segments, 0, Number.NaN)).toBe('string')
  })
})

describe('вставки', () => {
  const inserts: StoryboardInsert[] = [
    { media_id: 'a', at: 200, duration: 18 },
    { media_id: 'b', at: 560, duration: 25 },
  ]
  it('подпись и проверка пересечений', () => {
    expect(insertRange(inserts[0]!, 788)).toBe('с 3:20 по 3:38')
    expect(insertProblem(inserts, 0, 788)).toBeNull()
    expect(insertProblem([...inserts, { media_id: 'c', at: 210, duration: 5 }], 2, 788)).toContain(
      'Пересекается',
    )
    expect(insertProblem([{ media_id: 'c', at: 800, duration: 5 }], 0, 788)).toContain('за концом')
    expect(insertProblem([{ media_id: 'c', at: Number.NaN, duration: 5 }], 0, 788)).toContain(
      'м:сс',
    )
  })
})

describe('оценка', () => {
  it('заголовок, остаток лимита и подтверждение', () => {
    const est = estimate({})
    expect(estimateHeadline(est)).toBe('≈ 4,2 мин · ≈ $12,60')
    expect(estimateDetail(est, 'октября')).toBe(
      `720p, 3${NB}отрезка со спикером без вставок. Из лимита октября останется 33,8 мин из 60 мин.`,
    )
    expect(capPct(est)).toBeCloseTo(43.67, 1)
    expect(capLabel(est)).toBe('22 + 4,2 из 60 мин')
    expect(payConfirmText(est, 'октября')).toContain('4,2 мин гуся в 720p')
    expect(payConfirmText(est, 'октября')).toContain('останется 33,8 мин из 60 мин')
  })
  it('без гуся — бесплатно, причина сервера важнее', () => {
    expect(estimateHeadline(estimate({ goose_enabled: false, chunks: 0, inserts: 2 }))).toBe(
      'Без гуся · бесплатно',
    )
    expect(estimateDetail(estimate({ goose_enabled: false, chunks: 0, inserts: 2 }))).toContain(
      `2${NB}вставки`,
    )
    expect(estimateDetail(estimate({ goose_enabled: false, chunks: 0 }))).toContain('нечего')
    expect(
      estimateDetail(estimate({ allowed: false, reason: 'Лимит минут гуся на месяц исчерпан' })),
    ).toBe('Лимит минут гуся на месяц исчерпан')
    expect(capPct(estimate({ monthly_cap_sec: 0 }))).toBe(100)
  })
})

describe('ход и итог монтажа', () => {
  const job = (over: Partial<MediaJob>): MediaJob => ({
    id: 'j',
    media_id: 'm',
    kind: 'compose',
    status: 'running',
    params: {
      goose_enabled: true,
      resolution: '720p',
      chunks: [
        [0, 72],
        [400, 485],
      ],
      inserts: [{ media_id: 'i', at: 200, duration: 18 }],
    },
    result: {},
    error: null,
    attempts: 1,
    created_at: '2026-10-23T10:00:00Z',
    started_at: null,
    finished_at: null,
    ...over,
  })
  it('подписи стадий', () => {
    expect(composeProgress(null).text).toBe('запуск')
    expect(composeProgress(job({ status: 'queued' })).text).toBe('ждём очереди')
    expect(
      composeProgress(
        job({
          result: {
            progress: { stage: 'goose 2/3', pct: 40 },
            hedra: { chunks: [{ status: 'downloaded' }, { status: 'processing' }] },
          },
        }),
      ),
    ).toEqual({ pct: 40, text: 'гусь 2 из 3 · Hedra рендерит · готово 1' })
    expect(composeProgress(job({ result: { progress: { stage: 'voice 1/3', pct: 21 } } })).text).toBe(
      'голос для отрезка 1 из 3',
    )
    expect(composeProgress(job({ result: { progress: { stage: 'render', pct: 90 } } })).text).toBe(
      'склейка видео',
    )
  })
  it('итог берётся из снимка заказа и результата', () => {
    const done = job({
      status: 'done',
      result: {
        plan: { goose_seconds: 157, chunks: 2, inserts: 1, resolution: '720p' },
        billed_seconds: 157,
        cost_cents: 785,
      },
    })
    expect(composeSummary(done, 788)).toEqual({
      gooseEnabled: true,
      gooseChunks: 2,
      gooseSeconds: 157,
      inserts: 1,
      insertSeconds: 18,
      costCents: 785,
      billedSeconds: 157,
      resolution: '720p',
    })
    expect(composeSummary(null, 788)).toBeNull()
    const bars = composeBars(done, 788)
    expect(bars.map((b) => b.tone)).toEqual(['goose', 'goose', 'insert'])
  })
})
