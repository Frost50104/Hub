import { describe, expect, it } from 'vitest'

import {
  MAX_INTERVALS,
  capIntervals,
  classifyFlushError,
  coverageOf,
  countsAsWatched,
  displayPercent,
  isWatched,
  mergeIntervals,
  parseEcho,
  pickDuration,
  type Interval,
} from './videoWatch'

describe('countsAsWatched', () => {
  it('обычный шаг воспроизведения засчитывается', () => {
    expect(countsAsWatched(10, 10.25, false)).toBe(true)
  })

  it('большой разрыв БЕЗ перемотки засчитывается — это задушенный таймер', () => {
    // Фоновая вкладка: timeupdate раз в минуту, видео играло всё это время.
    expect(countsAsWatched(10, 70, false)).toBe(true)
  })

  it('перемотка не засчитывается, каким бы ни был шаг', () => {
    expect(countsAsWatched(10, 70, true)).toBe(false)
    expect(countsAsWatched(10, 10.3, true)).toBe(false)
  })

  it('перемотка назад не добавляет интервал', () => {
    expect(countsAsWatched(70, 10, false)).toBe(false)
    expect(countsAsWatched(10, 10, false)).toBe(false)
  })
})

describe('mergeIntervals', () => {
  it('смыкает щели короче 0,5 с и склеивает пересечения', () => {
    const src: Interval[] = [
      [0, 5],
      [5.3, 9],
      [8, 12],
    ]
    expect(mergeIntervals(src)).toEqual([[0, 12]])
  })

  it('щель длиннее 0,5 с остаётся дырой', () => {
    expect(
      mergeIntervals([
        [0, 5],
        [7, 9],
      ]),
    ).toEqual([
      [0, 5],
      [7, 9],
    ])
  })

  it('мусор отбрасывается', () => {
    expect(
      mergeIntervals([
        [5, 5],
        [9, 3],
        [-1, 2],
        [1, 2],
      ]),
    ).toEqual([[1, 2]])
  })

  it('порядок входа не важен', () => {
    expect(
      mergeIntervals([
        [10, 12],
        [0, 3],
      ]),
    ).toEqual([
      [0, 3],
      [10, 12],
    ])
  })
})

describe('coverageOf', () => {
  it('считает долю объединения', () => {
    expect(coverageOf([[0, 45]], 50)).toBeCloseTo(0.9)
  })

  it('пропущенная середина не засчитывается', () => {
    expect(
      coverageOf(
        [
          [0, 10],
          [40, 50],
        ],
        50,
      ),
    ).toBeCloseTo(0.4)
  })

  it('нулевая длительность — 0, а не NaN и не Infinity', () => {
    expect(coverageOf([[0, 10]], 0)).toBe(0)
    expect(coverageOf([], 0)).toBe(0)
  })

  it('сверху обрезано единицей', () => {
    expect(coverageOf([[0, 100]], 50)).toBe(1)
  })
})

describe('порог и показ', () => {
  it('isWatched сравнивает как сервер, без округления', () => {
    expect(isWatched(0.9)).toBe(true)
    expect(isWatched(0.8995)).toBe(false)
  })

  it('процент округляется ВНИЗ: полоса не обещает больше, чем засчитает гейт', () => {
    // 89,5% раньше показывались как 90% и зеленели, а сервер отвечал 409.
    expect(displayPercent(0.895)).toBe(89)
    expect(displayPercent(0.9)).toBe(90)
    expect(displayPercent(0.999)).toBe(99)
  })
})


describe('pickDuration', () => {
  it('конечная длительность берётся как есть', () => {
    expect(pickDuration(53.243, null)).toBe(53.243)
  })

  it('Infinity уходит на конец seekable', () => {
    // Пока не пришёл moov, duration = Infinity; в JSON он превращается в null
    // и ловил 422 на каждом пинге.
    expect(pickDuration(Infinity, 120)).toBe(120)
  })

  it('NaN тоже уходит на seekable', () => {
    expect(pickDuration(NaN, 60)).toBe(60)
  })

  it('оба нечитаемы → 0, и это не повод не слать интервалы', () => {
    expect(pickDuration(Infinity, null)).toBe(0)
    expect(pickDuration(NaN, Infinity)).toBe(0)
    expect(pickDuration(0, 0)).toBe(0)
    expect(pickDuration(-5, -1)).toBe(0)
  })

  it('хвост на ended при нечитаемой длительности не даёт NaN%', () => {
    // Регресс вчерашней правки: [x, Infinity] превращал покрытие в NaN,
    // и на экране горело «сейчас NaN%», а полоса ломала вёрстку.
    const duration = pickDuration(Infinity, null)
    const tail: Interval[] = duration > 0 ? [[10, duration]] : []
    expect(Number.isNaN(coverageOf(tail, duration))).toBe(false)
    expect(displayPercent(coverageOf(tail, duration))).toBe(0)
  })
})

describe('classifyFlushError', () => {
  it('нет ответа и 5xx — повторим', () => {
    expect(classifyFlushError(null)).toBe('retry')
    expect(classifyFlushError(0)).toBe('retry')
    expect(classifyFlushError(500)).toBe('retry')
    expect(classifyFlushError(429)).toBe('retry')
  })

  it('422/413 — повтор того же тела бесполезен', () => {
    expect(classifyFlushError(422)).toBe('poison')
    expect(classifyFlushError(413)).toBe('poison')
  })

  it('409/404 — состояние урока изменилось', () => {
    expect(classifyFlushError(409)).toBe('state')
    expect(classifyFlushError(404)).toBe('state')
  })

  it('401/403 — сессия', () => {
    expect(classifyFlushError(401)).toBe('auth')
    expect(classifyFlushError(403)).toBe('auth')
  })
})

describe('parseEcho', () => {
  it('разбирает ответ ручки', () => {
    expect(parseEcho({ coverage: 0.5, duration: 100, watched: false })).toEqual({
      coverage: 0.5,
      duration: 100,
      watched: false,
    })
  })

  it('204 от старого бэкенда переживаем', () => {
    // Окно deploy.sh: новый бандл уже отдан, сервис ещё не перезапущен.
    expect(parseEcho('')).toBeNull()
    expect(parseEcho(undefined)).toBeNull()
    expect(parseEcho({ nonsense: 1 })).toBeNull()
  })

  it('нечитаемая длительность приходит как null', () => {
    expect(parseEcho({ coverage: 0, duration: null, watched: false })?.duration).toBeNull()
  })
})

describe('capIntervals', () => {
  const many = (count: number, start = 0, step = 10): Interval[] =>
    Array.from({ length: count }, (_, i) => [start + i * step, start + i * step + 5])

  it('пока помещается — не теряем ничего, даже доли секунды', () => {
    const tiny: Interval[] = [
      [0, 50],
      [59.9, 60],
    ]
    expect(capIntervals(tiny, MAX_INTERVALS, 60)).toEqual(tiny)
  })

  it('переполнение ужимается до лимита', () => {
    expect(capIntervals(many(MAX_INTERVALS + 200), MAX_INTERVALS, 10_000)).toHaveLength(
      MAX_INTERVALS,
    )
  })

  it('хвост ролика не выбрасывается никогда', () => {
    const source = many(MAX_INTERVALS + 200)
    const capped = capIntervals(source, MAX_INTERVALS, 10_000)
    expect(capped[capped.length - 1]).toEqual(source[source.length - 1])
  })

  it('первыми уходят огрызки скраббинга', () => {
    const real = Array.from({ length: MAX_INTERVALS }, (_, i): Interval => [
      i * 100,
      i * 100 + 50,
    ])
    const crumbs = Array.from({ length: 40 }, (_, i): Interval => [
      i * 100 + 60,
      i * 100 + 60.1,
    ])
    const capped = capIntervals([...real, ...crumbs], MAX_INTERVALS, 60_000)
    expect(capped).toHaveLength(MAX_INTERVALS)
    expect(capped.every(([s, e]) => e - s > 1)).toBe(true)
  })

  it('идемпотентна', () => {
    const once = capIntervals(many(MAX_INTERVALS + 200), MAX_INTERVALS, 10_000)
    expect(capIntervals(once, MAX_INTERVALS, 10_000)).toEqual(once)
  })

  it('покрытие не растёт больше бюджета склейки (1%)', () => {
    const duration = 10_000
    const source = many(MAX_INTERVALS + 200)
    const before = coverageOf(mergeIntervals(source), duration)
    const after = coverageOf(capIntervals(source, MAX_INTERVALS, duration), duration)
    expect(after).toBeLessThanOrEqual(before + 0.01 + 1e-9)
  })

  it('детерминирована', () => {
    const source = many(MAX_INTERVALS + 200)
    expect(capIntervals(source, MAX_INTERVALS, 10_000)).toEqual(
      capIntervals(source, MAX_INTERVALS, 10_000),
    )
  })
})
