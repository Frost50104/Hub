import { describe, expect, it } from 'vitest'

import type { AuthState } from './authState'
import {
  clearProgressParams,
  type EmployeeProgressRow,
  EMPTY_PROGRESS_FILTERS,
  accountNote,
  barSegmented,
  filterProgressRows,
  mandatoryShort,
  progressBucket,
  progressCaption,
  progressCounts,
  progressMetaLine,
  progressPillClass,
  progressPct,
  resolveProgressFilters,
  resolveProgressSort,
  setProgressParams,
  sortProgressRows,
} from './learnProgress'

const NBSP = ' '

function row(over: Partial<EmployeeProgressRow> = {}): EmployeeProgressRow {
  return {
    profile_id: over.profile_id ?? Math.random().toString(36).slice(2),
    full_name: 'Пётр Попов',
    email: 'pp@uppetit.ru',
    position_id: 'pos-1',
    position_name: 'Продавец-бариста',
    store_id: 'store-1',
    store_name: 'Невская 3',
    has_account: true,
    auth_state: 'active' as AuthState,
    mandatory_total: 6,
    mandatory_done: 0,
    mandatory_pct: 0,
    courses_available: 6,
    courses_started: 0,
    courses_completed: 0,
    quizzes_passed: 0,
    certificates: 0,
    points: 0,
    last_activity_at: '2026-09-14T10:00:00Z',
    ...over,
  }
}

describe('progressBucket', () => {
  it('различает три состояния при непустом знаменателе', () => {
    expect(progressBucket({ mandatory_total: 6, mandatory_done: 0 })).toBe('none')
    expect(progressBucket({ mandatory_total: 6, mandatory_done: 3 })).toBe('partial')
    expect(progressBucket({ mandatory_total: 6, mandatory_done: 6 })).toBe('done')
  })

  it('«0 из 0» — отдельная корзина, а не «завершил всё»', () => {
    // Знаменатель приходит из аудиторий: офисный сотрудник вне обязательных
    // честно имеет ноль. Схлопни в done — и KPI вырастет на ровном месте.
    expect(progressBucket({ mandatory_total: 0, mandatory_done: 0 })).toBe(
      'nothing_assigned',
    )
  })

  it('рассинхрон снапшота не роняет', () => {
    expect(progressBucket({ mandatory_total: 6, mandatory_done: 7 })).toBe('done')
  })
})

describe('progressPillClass', () => {
  it('цветной исход ровно один — пройдено', () => {
    expect(progressPillClass('done')).toContain('bg-green-deep')
  })

  it('остальные нейтральны: 136 красных строк из 315 обесценили бы красный', () => {
    for (const bucket of ['none', 'partial', 'nothing_assigned'] as const) {
      expect(progressPillClass(bucket)).toBe('bg-surface text-text2')
    }
  })
})

describe('mandatoryShort', () => {
  it('ставит неразрывный пробел', () => {
    expect(mandatoryShort(4, 6)).toBe(`4${NBSP}из 6`)
  })

  it('«нечего проходить» — прочерк, а не «0 из 0»', () => {
    expect(mandatoryShort(0, 0)).toBe('—')
  })

  it('клампит протухший снапшот', () => {
    expect(mandatoryShort(9, 8)).toBe(`8${NBSP}из 8`)
  })
})

describe('progressPct', () => {
  it('считает и клампит', () => {
    expect(progressPct(0, 6)).toBe(0)
    expect(progressPct(3, 6)).toBe(50)
    expect(progressPct(9, 8)).toBe(100)
    expect(progressPct(0, 0)).toBe(0)
  })
})

describe('accountNote', () => {
  it('«нет учётки» утверждается только когда сервер в этом уверен', () => {
    expect(accountNote(row({ auth_state: 'no_account' as AuthState }))).toBe(
      'нет учётки — в Hub не заходил',
    )
  })

  it('приглашённый — не «без учётки»: движение уже есть', () => {
    expect(accountNote(row({ auth_state: 'invited' as AuthState }))).toBe(
      'приглашён(а) в auth — ещё не принял(а)',
    )
  })

  it('not_linked ≠ no_account — до синка так говорить нельзя', () => {
    expect(accountNote(row({ auth_state: 'not_linked' as AuthState }))).toBe(
      'в Hub не заходил',
    )
  })

  it('учётка есть, но человек не входил', () => {
    expect(
      accountNote(row({ auth_state: 'not_logged_in' as AuthState, last_activity_at: null })),
    ).toBe('в Hub не заходил')
  })

  it('у активного примечания нет', () => {
    expect(accountNote(row())).toBeNull()
  })
})

describe('progressMetaLine', () => {
  it('склоняет тесты', () => {
    expect(progressMetaLine(row({ courses_started: 3, quizzes_passed: 1 }))).toContain(
      `1${NBSP}тест`,
    )
    expect(progressMetaLine(row({ courses_started: 3, quizzes_passed: 2 }))).toContain(
      `2${NBSP}теста`,
    )
    expect(progressMetaLine(row({ courses_started: 3, quizzes_passed: 12 }))).toContain(
      `12${NBSP}тестов`,
    )
  })

  it('пустой прогресс называет словом, а не нулями', () => {
    const line = progressMetaLine(row())
    expect(line).toContain('Ничего не начато')
    expect(line).not.toContain('начато 0')
  })

  it('дописывает примечание про учётку', () => {
    const line = progressMetaLine(row({ auth_state: 'no_account' as AuthState }))
    expect(line).toContain('нет учётки')
  })
})

describe('compareProgress(lagging)', () => {
  it('отстающие выше завершивших', () => {
    const sorted = sortProgressRows(
      [
        row({ profile_id: 'done', mandatory_done: 6 }),
        row({ profile_id: 'none', mandatory_done: 0 }),
        row({ profile_id: 'half', mandatory_done: 3 }),
      ],
      'lagging',
    )
    expect(sorted.map((r) => r.profile_id)).toEqual(['none', 'half', 'done'])
  })

  it('сравнивает ДОЛЮ, а не абсолют: 4 из 8 отстаёт сильнее, чем 4 из 6', () => {
    const sorted = sortProgressRows(
      [
        row({ profile_id: 'of6', mandatory_total: 6, mandatory_done: 4 }),
        row({ profile_id: 'of8', mandatory_total: 8, mandatory_done: 4 }),
      ],
      'lagging',
    )
    expect(sorted[0]?.profile_id).toBe('of8')
  })

  it('«нечего проходить» уходит в самый хвост', () => {
    const sorted = sortProgressRows(
      [
        row({ profile_id: 'empty', mandatory_total: 0, mandatory_done: 0 }),
        row({ profile_id: 'done', mandatory_done: 6 }),
      ],
      'lagging',
    )
    expect(sorted.map((r) => r.profile_id)).toEqual(['done', 'empty'])
  })

  it('при равном нуле выше тот, у кого есть учётка', () => {
    const sorted = sortProgressRows(
      [
        row({ profile_id: 'noacct', has_account: false, last_activity_at: null }),
        row({ profile_id: 'acct', has_account: true }),
      ],
      'lagging',
    )
    expect(sorted[0]?.profile_id).toBe('acct')
  })

  it('детерминирован: повторная сортировка не меняет порядок', () => {
    const rows = [
      row({ profile_id: 'a', full_name: 'Азов' }),
      row({ profile_id: 'b', full_name: 'Бобров' }),
      row({ profile_id: 'c', full_name: 'Власов' }),
    ]
    const once = sortProgressRows(rows, 'lagging').map((r) => r.profile_id)
    const twice = sortProgressRows(sortProgressRows(rows, 'lagging'), 'lagging').map(
      (r) => r.profile_id,
    )
    expect(twice).toEqual(once)
  })
})

describe('compareProgress(name|store)', () => {
  it('«Ё» сортируется как «Е», а не улетает в конец алфавита', () => {
    // sensitivity: 'base' приравнивает Ё к Е, поэтому дальше решает вторая
    // буква: «Елисеев» < «Ёлкина». Важно ровно то, что обе фамилии стоят
    // рядом в начале, а не «Ёлкина» после «Яшина».
    const sorted = sortProgressRows(
      [
        row({ profile_id: 'ya', full_name: 'Яшин' }),
        row({ profile_id: 'yo', full_name: 'Ёлкина' }),
        row({ profile_id: 'e', full_name: 'Елисеев' }),
      ],
      'name',
    )
    expect(sorted.map((r) => r.profile_id)).toEqual(['e', 'yo', 'ya'])
  })

  it('без точки — в хвост', () => {
    const sorted = sortProgressRows(
      [
        row({ profile_id: 'office', store_name: null }),
        row({ profile_id: 'shop', store_name: 'Аврора' }),
      ],
      'store',
    )
    expect(sorted.map((r) => r.profile_id)).toEqual(['shop', 'office'])
  })
})

describe('filterProgressRows', () => {
  it('находит по имени в обратном порядке слов', () => {
    const rows = [row({ profile_id: 'pp', full_name: 'Пётр Попов' })]
    const found = filterProgressRows(rows, { ...EMPTY_PROGRESS_FILTERS, q: 'попов петр' })
    expect(found).toHaveLength(1)
  })

  it('ищет и по точке с должностью', () => {
    const rows = [row({ profile_id: 'x', store_name: 'Галерея' })]
    expect(
      filterProgressRows(rows, { ...EMPTY_PROGRESS_FILTERS, q: 'галерея' }),
    ).toHaveLength(1)
  })

  it('НЕ обрезает выдачу — потолок однажды спрятал 84% справочника', () => {
    const many = Array.from({ length: 300 }, (_, i) =>
      row({ profile_id: `p${i}`, full_name: `Сотрудник ${i}` }),
    )
    expect(filterProgressRows(many, EMPTY_PROGRESS_FILTERS)).toHaveLength(300)
  })

  it('«только с учётной записью» оставляет тех, кто просто не входил', () => {
    const rows = [
      row({ profile_id: 'never', auth_state: 'not_logged_in' as AuthState, has_account: true }),
      row({ profile_id: 'none', auth_state: 'no_account' as AuthState, has_account: false }),
    ]
    const found = filterProgressRows(rows, {
      ...EMPTY_PROGRESS_FILTERS,
      linkedOnly: true,
    })
    expect(found.map((r) => r.profile_id)).toEqual(['never'])
  })

  it('должность фильтрует по id, а не по «должность вообще есть»', () => {
    // Регрессия: первая версия проверяла `position_name !== null` и пропускала
    // всех, у кого должность просто заполнена.
    const rows = [
      row({ profile_id: 'barista', position_id: 'pos-1' }),
      row({ profile_id: 'admin', position_id: 'pos-2' }),
    ]
    const found = filterProgressRows(rows, {
      ...EMPTY_PROGRESS_FILTERS,
      positionId: 'pos-1',
    })
    expect(found.map((r) => r.profile_id)).toEqual(['barista'])
  })

  it('корзина и точка складываются по И', () => {
    const rows = [
      row({ profile_id: 'hit', store_id: 's1', mandatory_done: 0 }),
      row({ profile_id: 'other-store', store_id: 's2', mandatory_done: 0 }),
      row({ profile_id: 'other-bucket', store_id: 's1', mandatory_done: 6 }),
    ]
    const found = filterProgressRows(rows, {
      ...EMPTY_PROGRESS_FILTERS,
      storeId: 's1',
      bucket: 'none',
    })
    expect(found.map((r) => r.profile_id)).toEqual(['hit'])
  })
})

describe('progressCounts', () => {
  it('корзины в сумме дают весь набор', () => {
    const rows = [
      row({ mandatory_done: 6 }),
      row({ mandatory_done: 3 }),
      row({ mandatory_done: 0 }),
      row({ mandatory_total: 0, mandatory_done: 0 }),
    ]
    const c = progressCounts(rows)
    expect(c.done + c.partial + c.none + c.nothingAssigned).toBe(rows.length)
  })

  it('считает тех, кто не может учиться', () => {
    const c = progressCounts([
      row({ has_account: false, last_activity_at: null }),
      row(),
    ])
    expect(c.noAccount).toBe(1)
    expect(c.neverActive).toBe(1)
  })
})

describe('progressCaption', () => {
  it('без фильтра — общий счёт', () => {
    expect(
      progressCaption({ matched: 315, loaded: 315, total: 315, filtered: false }),
    ).toBe('Всего: 315')
  })

  it('с фильтром — сколько показано', () => {
    expect(
      progressCaption({ matched: 12, loaded: 315, total: 315, filtered: true }),
    ).toBe('Показано 12 из 315')
  })

  it('при неполной выдаче говорит о разрыве, а не «Всего»', () => {
    const caption = progressCaption({
      matched: 300,
      loaded: 300,
      total: 315,
      filtered: false,
    })
    expect(caption).not.toContain('Всего: 315')
    expect(caption).toContain('300')
  })

  it('пустой результат фильтра не превращается во «Всего: 0»', () => {
    expect(
      progressCaption({ matched: 0, loaded: 315, total: 315, filtered: true }),
    ).toBe('Показано 0 из 315')
  })
})

describe('barSegmented', () => {
  it('сегменты только при обозримом знаменателе', () => {
    expect(barSegmented(6)).toBe(true)
    expect(barSegmented(0)).toBe(false)
    expect(barSegmented(40)).toBe(false)
  })
})

describe('адрес страницы', () => {
  it('пустые параметры дают дефолты', () => {
    const params = new URLSearchParams()
    expect(resolveProgressFilters(params)).toEqual(EMPTY_PROGRESS_FILTERS)
    expect(resolveProgressSort(params)).toBe('lagging')
  })

  it('мусор в сортировке откатывается на дефолт', () => {
    expect(resolveProgressSort(new URLSearchParams('sort=%D0%BC%D1%83%D1%81%D0%BE%D1%80'))).toBe(
      'lagging',
    )
    expect(resolveProgressFilters(new URLSearchParams('bucket=xxx')).bucket).toBeNull()
  })

  it('СОХРАНЯЕТ tab — иначе вкладка отскочит на первую доступную', () => {
    const next = setProgressParams(new URLSearchParams('tab=progress'), { q: 'петров' })
    expect(next.get('tab')).toBe('progress')
    expect(next.get('q')).toBe('петров')
  })

  it('дефолты в адрес не пишет', () => {
    const next = setProgressParams(new URLSearchParams('tab=progress'), {
      sort: 'lagging',
      q: '',
    })
    expect(next.has('sort')).toBe(false)
    expect(next.has('q')).toBe(false)
  })

  it('сброс чистит только свои ключи', () => {
    const next = clearProgressParams(new URLSearchParams('tab=progress&q=a&store=s&sort=name'))
    expect(next.get('tab')).toBe('progress')
    expect(next.get('sort')).toBe('name')
    expect(next.has('q')).toBe(false)
    expect(next.has('store')).toBe(false)
  })

  it('туда-обратно: разбор читает то, что записал setProgressParams', () => {
    const written = setProgressParams(new URLSearchParams('tab=progress'), {
      q: 'галерея',
      storeId: 's1',
      linkedOnly: true,
      bucket: 'none',
    })
    expect(resolveProgressFilters(written)).toEqual({
      q: 'галерея',
      storeId: 's1',
      positionId: null,
      linkedOnly: true,
      bucket: 'none',
    })
  })
})
