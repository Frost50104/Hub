import { describe, expect, it } from 'vitest'

import {
  GAP_CLOSE,
  MAX_INTERVALS,
  bodySignature,
  buildWatchView,
  capIntervals,
  classifyFlushError,
  coverageOf,
  countsAsWatched,
  displayPercent,
  firstGap,
  formatClock,
  isWatched,
  mergeIntervals,
  parseEcho,
  pickDuration,
  serverCoverageFloor,
  watchSegments,
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
  it('смыкает короткие щели и склеивает пересечения', () => {
    const src: Interval[] = [
      [0, 5],
      [5.3, 9],
      [8, 12],
    ]
    expect(mergeIntervals(src)).toEqual([[0, 12]])
  })

  it('щель длиннее склейки остаётся дырой', () => {
    expect(
      mergeIntervals([
        [0, 5],
        [8, 9],
      ]),
    ).toEqual([
      [0, 5],
      [8, 9],
    ])
  })

  it('микро-дыры после перемотки затягиваются', () => {
    // Живая запись прода: две дыры, 1.9 с и 1.0 с — след тапа по полосе, а не
    // пропущенный кусок. При пороге 0.5 с они стоили человеку 5% покрытия.
    expect(
      mergeIntervals([
        [0, 33.5],
        [35.4, 36.8],
        [37.8, 56.9],
      ]),
    ).toEqual([[0, 56.9]])
  })

  it('граница склейки — ровно константа', () => {
    const edge: Interval[] = [
      [0, 10],
      [10 + GAP_CLOSE, 20],
    ]
    expect(mergeIntervals(edge)).toEqual([[0, 20]])
    expect(
      mergeIntervals([
        [0, 10],
        [10 + GAP_CLOSE + 0.1, 20],
      ]),
    ).toHaveLength(2)
  })

  it('на общем наборе даёт ТО ЖЕ, что сервер', () => {
    // Дубль `test_same_result_as_the_client` из tests/unit/test_video_progress.py.
    // Клиент считает процент из своей копии, сервер — из своей; разъедься
    // правила склейки, на экране будет одно число, в гейте другое.
    expect(
      mergeIntervals([
        [0, 10],
        [11.5, 20],
        [22.5, 30],
        [30, 31],
      ]),
    ).toEqual([
      [0, 20],
      [22.5, 31],
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

describe('watchSegments', () => {
  it('рисует дыру там, где она есть', () => {
    const segs = watchSegments(
      [
        [0, 25],
        [30, 50],
      ],
      50,
    )
    expect(segs).toEqual([
      { leftPct: 0, widthPct: 50 },
      { leftPct: 60, widthPct: 40 },
    ])
  })

  it('сумма ширин равна покрытию — полоса не спорит с числом под ней', () => {
    const intervals: Interval[] = [
      [0, 10],
      [20, 30],
      [45, 50],
    ]
    const sum = watchSegments(intervals, 50).reduce((acc, s) => acc + s.widthPct, 0)
    expect(sum).toBeCloseTo(coverageOf(intervals, 50) * 100, 6)
  })

  it('ничего не вылезает за 100%', () => {
    // Интервалы длиннее ролика — обычная погрешность отчёта.
    const segs = watchSegments([[0, 80]], 50)
    expect(segs).toEqual([{ leftPct: 0, widthPct: 100 }])
    for (const s of segs) expect(s.leftPct + s.widthPct).toBeLessThanOrEqual(100)
  })

  it('нулевая длительность не даёт NaN, а просто пустую полосу', () => {
    expect(watchSegments([[0, 10]], 0)).toEqual([])
    expect(watchSegments([], 50)).toEqual([])
  })
})

describe('firstGap', () => {
  it('дыра в середине — это пропуск', () => {
    expect(
      firstGap(
        [
          [0, 20],
          [30, 50],
        ],
        50,
      ),
    ).toEqual({ at: 20, kind: 'skipped' })
  })

  it('не начал с начала — тоже пропуск', () => {
    expect(firstGap([[10, 50]], 50)).toEqual({ at: 0, kind: 'skipped' })
  })

  it('недосмотренный хвост — не перемотка', () => {
    // Самый частый случай: остановился, не дойдя до конца. Кнопка нужна и тут,
    // а вот обвинять в перемотке нельзя — отсюда отдельный kind.
    expect(firstGap([[0, 40]], 50)).toEqual({ at: 40, kind: 'tail' })
  })

  it('дыра внутри важнее хвоста', () => {
    expect(
      firstGap(
        [
          [0, 10],
          [20, 40],
        ],
        50,
      ),
    ).toEqual({ at: 10, kind: 'skipped' })
  })

  it('дыра короче склейки не считается', () => {
    expect(firstGap([[0, 49]], 50)).toBeNull()
    expect(
      firstGap(
        [
          [0, 20],
          [21, 50],
        ],
        50,
      ),
    ).toBeNull()
  })

  it('всё просмотрено — молчит', () => {
    expect(firstGap([[0, 50]], 50)).toBeNull()
    expect(firstGap([[0, 60]], 50)).toBeNull()
  })

  it('без длительности решать нечего', () => {
    expect(firstGap([[0, 10]], 0)).toBeNull()
    expect(firstGap([], 50)).toEqual({ at: 0, kind: 'tail' })
  })
})

describe('formatClock', () => {
  it('секунды в м:сс', () => {
    expect(formatClock(0)).toBe('0:00')
    expect(formatClock(9.7)).toBe('0:09')
    expect(formatClock(95)).toBe('1:35')
    expect(formatClock(3600)).toBe('60:00')
  })

  it('мусор не даёт NaN:NaN', () => {
    expect(formatClock(-5)).toBe('0:00')
    expect(formatClock(NaN)).toBe('0:00')
  })
})

describe('serverCoverageFloor', () => {
  it('обычно это просто серверное число', () => {
    expect(serverCoverageFloor({ coverage: 0.62, duration: 56.9, watched: false })).toBe(
      0.62,
    )
  })

  it('вердикт сервера сильнее его же числа', () => {
    // Если формулы когда-нибудь разойдутся, на экране обязано остаться
    // «досмотрено», а не «сейчас 89%» при зелёном гейте.
    expect(serverCoverageFloor({ coverage: 0.89, duration: 100, watched: true })).toBe(0.9)
    expect(serverCoverageFloor({ coverage: 0.97, duration: 100, watched: true })).toBe(0.97)
  })
})

describe('bodySignature', () => {
  it('одинаковое тело — одинаковая подпись', () => {
    const a: Interval[] = [
      [0, 10],
      [40, 50],
    ]
    expect(bodySignature(a, 50)).toBe(bodySignature([...a], 50))
  })

  it('досмотр ДЫРЫ В СЕРЕДИНЕ меняет подпись', () => {
    // Главный регресс: кусков по-прежнему два и конец последнего тот же, но
    // просмотрено больше. Со старой подписью уходной флаш на `pagehide` считал
    // такое тело дубликатом и молча его не слал — секунды терялись.
    const before: Interval[] = [
      [0, 10],
      [40, 50],
    ]
    const after: Interval[] = [
      [0, 25],
      [40, 50],
    ]
    expect(bodySignature(after, 50)).not.toBe(bodySignature(before, 50))
  })

  it('новый кусок и смена длительности тоже меняют подпись', () => {
    const base: Interval[] = [[0, 10]]
    expect(bodySignature([...base, [20, 30]], 50)).not.toBe(bodySignature(base, 50))
    expect(bodySignature(base, null)).not.toBe(bodySignature(base, 50))
  })

  it('пустой список подписывается без падения', () => {
    expect(bodySignature([], null)).toBe('0:0.000:0:x')
  })
})

describe('buildWatchView', () => {
  const intervals: Interval[] = [
    [0, 5.9],
    [25.9, 36.4],
  ]
  const duration = 56.889

  it('показывает большее из локального и серверного', () => {
    expect(buildWatchView(intervals, duration, 0).coverage).toBeCloseTo(
      coverageOf(intervals, duration),
      6,
    )
    expect(buildWatchView(intervals, duration, 0.95).coverage).toBe(0.95)
  })

  it('округление ручки до 4 знаков НЕ гасит подсказку', () => {
    // Ручка отвечает round(coverage, 4), поэтому её число почти всегда чуть
    // больше локального. С порогом «строго не больше» кнопка «К
    // непросмотренному» исчезала после первого же пинга (staging, 25.08).
    const local = coverageOf(intervals, duration)
    const rounded = Math.round(local * 10_000) / 10_000
    const view = buildWatchView(intervals, duration, rounded)
    expect(view.gap).toEqual({ at: 5.9, kind: 'skipped' })
  })

  it('сервер знает заметно больше — карта неполная, звать некуда', () => {
    // Второе устройство или устаревший снимок урока: где именно дыра, мы не
    // знаем, и отправили бы пересматривать засчитанное.
    expect(buildWatchView(intervals, duration, 0.62).gap).toBeNull()
  })

  it('без длительности не рисует ни сегментов, ни подсказки', () => {
    const view = buildWatchView(intervals, 0, 0)
    expect(view.segments).toEqual([])
    expect(view.gap).toBeNull()
    expect(view.coverage).toBe(0)
  })
})
