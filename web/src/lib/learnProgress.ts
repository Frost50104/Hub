/**
 * Правила экрана «Прогресс сотрудников» — корзины, порядок, фильтр, подписи.
 *
 * Всё чистое и здесь, потому что vitest в этом проекте бежит без jsdom:
 * компонент не покрыть, а ошибиться в сортировке и в словах «нет учётки»
 * очень легко. Замеры прода, из-за которых экран устроен именно так:
 * из 315 активных карточек 134 человека ни разу не заходили в Hub, а из 181
 * зашедшего 136 не начали ни одного обязательного курса. То есть «отсортируй
 * по возрастанию прогресса» даёт 134 строки подряд у тех, кто и не мог
 * учиться, и хоронит тех, с кем действительно надо разговаривать.
 */

import type { AuthState } from './authState'
import { optionMatches, queryTokens } from './selectOptions'
import { nbsp, plural } from './typography'

export interface EmployeeProgressRow {
  profile_id: string
  full_name: string
  email: string
  position_id: string | null
  position_name: string | null
  store_id: string | null
  store_name: string | null
  has_account: boolean
  auth_state: AuthState
  mandatory_total: number
  mandatory_done: number
  mandatory_pct: number | null
  courses_available: number
  courses_started: number
  courses_completed: number
  quizzes_passed: number
  certificates: number
  points: number
  last_activity_at: string | null
}

// ─── Корзины ─────────────────────────────────────────────────────────────────

/**
 * `nothing_assigned` — отдельная корзина, а не «завершил всё».
 *
 * Знаменатель приходит из аудиторий, и офисный сотрудник вне обязательных
 * аудиторий честно имеет ноль. Схлопни его в `done` — и KPI «завершили всё»
 * вырастет на ровном месте, а сортировка отправит этих людей вниз по неверной
 * причине.
 */
export type ProgressBucket = 'nothing_assigned' | 'none' | 'partial' | 'done'

export const PROGRESS_BUCKETS: { key: ProgressBucket; label: string }[] = [
  { key: 'none', label: 'Не начинали' },
  { key: 'partial', label: 'В процессе' },
  { key: 'done', label: 'Завершили' },
  { key: 'nothing_assigned', label: 'Нечего проходить' },
]

export function progressBucket(
  row: Pick<EmployeeProgressRow, 'mandatory_total' | 'mandatory_done'>,
): ProgressBucket {
  if (row.mandatory_total <= 0) return 'nothing_assigned'
  if (row.mandatory_done >= row.mandatory_total) return 'done'
  if (row.mandatory_done <= 0) return 'none'
  return 'partial'
}

/** Человек физически может учиться только после первого входа в Hub. */
export function canLearn(row: EmployeeProgressRow): boolean {
  return row.last_activity_at !== null
}

// ─── Пилюля состояния ────────────────────────────────────────────────────────

export function progressPillLabel(bucket: ProgressBucket): string {
  switch (bucket) {
    case 'done':
      return 'пройдено'
    case 'partial':
      return 'в процессе'
    case 'none':
      return 'не начинал'
    default:
      return 'нет обязательных'
  }
}

/**
 * Цветных исходов ровно два, и это не вкусовщина.
 *
 * Спека Claude Design: «пройденное приглушается, а не подсвечивается», плотная
 * заливка + краска `--bg` вместо тинта с цветным текстом (амбер-на-амбере даёт
 * 1,73:1 при норме 4,5:1 для 11px), нейтральный бейдж — `--surface` с `text2`,
 * потому что `text3` на мелком кегле даёт 2,7:1. Красный зарезервирован за
 * просрочкой: 136 красных строк из 315 обесценили бы красный на всём экране.
 */
export function progressPillClass(bucket: ProgressBucket): string {
  if (bucket === 'done') return 'bg-green-deep text-bg'
  return 'bg-surface text-text2'
}

// ─── Полоса и числа ──────────────────────────────────────────────────────────

/**
 * Выше этого знаменателя сегменты превращаются в кашу (и в тысячи узлов на
 * список), поэтому рисуем сплошную полосу. Сегодня на проде знаменатель 6–8.
 */
export const BAR_SEGMENT_CAP = 12

export function barSegmented(total: number): boolean {
  return total > 0 && total <= BAR_SEGMENT_CAP
}

export function progressPct(done: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((Math.min(done, total) / total) * 100)
}

/**
 * «4 из 6» — дробь, а не процент: знаменатель у каждого свой (6, 7 или 8),
 * и «67%» у двоих разных людей означало бы разное число курсов.
 *
 * Кламп обязателен: `course_progress.lessons_total` — денормализация, которую
 * переписывает только завершение урока, поэтому «9 из 8» встречается.
 */
export function mandatoryShort(done: number, total: number): string {
  if (total <= 0) return '—'
  return nbsp(`${Math.min(done, total)} из ${total}`)
}

// ─── Подписи строки ──────────────────────────────────────────────────────────

/**
 * Хвост метастроки про учётку.
 *
 * `not_linked` ≠ `no_account`: до первого staff-sync утверждать «без учётки»
 * нельзя (см. `authState.ts`) — непривязанная карточка может принадлежать
 * человеку с живой учёткой, который просто не входил.
 */
export function accountNote(row: EmployeeProgressRow): string | null {
  if (row.auth_state === 'no_account') return 'нет учётки — в Hub не заходил'
  if (row.auth_state === 'not_linked') return 'в Hub не заходил'
  if (row.auth_state === 'blocked') return 'учётка заблокирована'
  if (row.auth_state === 'deleted') return 'учётка удалена'
  if (!canLearn(row)) return 'в Hub не заходил'
  return null
}

export function orgLine(row: EmployeeProgressRow): string {
  return [row.store_name, row.position_name].filter(Boolean).join(' · ') || '—'
}

/** «Всего: начато 7, завершено 5 · сдано 12 тестов · нет учётки…» */
export function progressMetaLine(row: EmployeeProgressRow): string {
  const parts: string[] = []
  if (row.courses_started === 0) {
    parts.push('Ничего не начато')
  } else {
    parts.push(
      `Всего: начато ${row.courses_started}, завершено ${row.courses_completed}`,
    )
  }
  if (row.quizzes_passed > 0) {
    parts.push(`сдано ${plural(row.quizzes_passed, 'тест', 'теста', 'тестов')}`)
  }
  const note = accountNote(row)
  if (note) parts.push(note)
  return parts.join(' · ')
}

export function progressAria(row: EmployeeProgressRow): string {
  const short =
    row.mandatory_total > 0
      ? `обязательных пройдено ${row.mandatory_done} из ${row.mandatory_total}`
      : 'обязательных курсов нет'
  return `${row.full_name}: ${short}`
}

// ─── Фильтр ──────────────────────────────────────────────────────────────────

export interface ProgressFilters {
  q: string
  storeId: string | null
  positionId: string | null
  /** Только те, у кого учётка привязана. `no_account`/`not_linked` отпадают. */
  linkedOnly: boolean
  bucket: ProgressBucket | null
}

export const EMPTY_PROGRESS_FILTERS: ProgressFilters = {
  q: '',
  storeId: null,
  positionId: null,
  linkedOnly: false,
  bucket: null,
}

export function hasActiveFilters(f: ProgressFilters): boolean {
  return (
    f.q.trim() !== '' ||
    f.storeId !== null ||
    f.positionId !== null ||
    f.linkedOnly ||
    f.bucket !== null
  )
}

export function matchesProgressFilters(
  row: EmployeeProgressRow,
  f: ProgressFilters,
): boolean {
  if (f.storeId !== null && row.store_id !== f.storeId) return false
  if (f.positionId !== null && row.position_id !== f.positionId) return false
  if (f.bucket !== null && progressBucket(row) !== f.bucket) return false
  // «Есть учётка» — про привязку, а не про вход: `not_logged_in` остаётся.
  if (f.linkedOnly && !row.has_account) return false
  const tokens = queryTokens(f.q)
  if (tokens.length === 0) return true
  return optionMatches(
    {
      value: row.profile_id,
      label: row.full_name,
      meta: [row.email, row.store_name, row.position_name]
        .filter(Boolean)
        .join(' '),
    },
    tokens,
  )
}

/**
 * Фильтр БЕЗ потолка выдачи — решение владельца 16.09 после живого бага:
 * потолок в 50 строк спрятал 84% справочника, и «Пётр Попов», 246-й из 313 по
 * алфавиту, просто не находился.
 */
export function filterProgressRows(
  rows: readonly EmployeeProgressRow[],
  f: ProgressFilters,
): EmployeeProgressRow[] {
  return rows.filter((r) => matchesProgressFilters(r, f))
}

// ─── Порядок ─────────────────────────────────────────────────────────────────

export type ProgressSort = 'lagging' | 'name' | 'store'

export const PROGRESS_SORTS: { key: ProgressSort; label: string }[] = [
  { key: 'lagging', label: 'Отстающие сверху' },
  { key: 'name', label: 'По алфавиту' },
  { key: 'store', label: 'По магазину' },
]

/**
 * Один коллятор на модуль: на 315 строках сравнений тысячи, а
 * `a.localeCompare(b, 'ru')` создаёт `Intl.Collator` на каждый вызов.
 * `sensitivity: 'base'` ставит «Ёлкину» рядом с «Елкиной», а не в конец.
 */
const collator = new Intl.Collator('ru', { sensitivity: 'base' })

function byName(a: EmployeeProgressRow, b: EmployeeProgressRow): number {
  return collator.compare(a.full_name, b.full_name)
}

export function compareProgress(
  sort: ProgressSort,
): (a: EmployeeProgressRow, b: EmployeeProgressRow) => number {
  if (sort === 'name') return byName
  if (sort === 'store') {
    return (a, b) => {
      const sa = a.store_name ?? ''
      const sb = b.store_name ?? ''
      if (sa === '' && sb !== '') return 1
      if (sb === '' && sa !== '') return -1
      const byStore = collator.compare(sa, sb)
      return byStore !== 0 ? byStore : byName(a, b)
    }
  }
  return (a, b) => {
    // 1. Кому нечего проходить — в хвост: он не отстающий.
    const emptyA = a.mandatory_total <= 0
    const emptyB = b.mandatory_total <= 0
    if (emptyA !== emptyB) return emptyA ? 1 : -1
    if (!emptyA) {
      // 2. Доля, а не абсолют: 4 из 8 отстаёт сильнее, чем 4 из 6.
      const ratioA = Math.min(a.mandatory_done, a.mandatory_total) / a.mandatory_total
      const ratioB = Math.min(b.mandatory_done, b.mandatory_total) / b.mandatory_total
      if (ratioA !== ratioB) return ratioA - ratioB
    }
    // 3. С учёткой выше: его можно попросить сегодня, а карточку без входа
    //    заводит HR — это другая работа.
    if (a.has_account !== b.has_account) return a.has_account ? -1 : 1
    // 4. Кто заходил позже — выше: «ходит в Hub, но не учится» действеннее.
    const ta = a.last_activity_at ?? ''
    const tb = b.last_activity_at ?? ''
    if (ta !== tb) return ta < tb ? 1 : -1
    return byName(a, b)
  }
}

export function sortProgressRows(
  rows: readonly EmployeeProgressRow[],
  sort: ProgressSort,
): EmployeeProgressRow[] {
  return [...rows].sort(compareProgress(sort))
}

// ─── Счётчики и подпись ──────────────────────────────────────────────────────

export interface ProgressCounts {
  total: number
  done: number
  partial: number
  none: number
  nothingAssigned: number
  noAccount: number
  neverActive: number
}

export function progressCounts(
  rows: readonly EmployeeProgressRow[],
): ProgressCounts {
  const counts: ProgressCounts = {
    total: rows.length,
    done: 0,
    partial: 0,
    none: 0,
    nothingAssigned: 0,
    noAccount: 0,
    neverActive: 0,
  }
  for (const row of rows) {
    const bucket = progressBucket(row)
    if (bucket === 'done') counts.done += 1
    else if (bucket === 'partial') counts.partial += 1
    else if (bucket === 'none') counts.none += 1
    else counts.nothingAssigned += 1
    if (!row.has_account) counts.noAccount += 1
    if (!canLearn(row)) counts.neverActive += 1
  }
  return counts
}

/**
 * Подпись над таблицей по правилу `employeeListCaption`: число над списком
 * никогда не должно спорить с числом строк в нём.
 */
export function progressCaption(info: {
  matched: number
  loaded: number
  total: number
  filtered: boolean
}): string {
  if (info.loaded < info.total) {
    return `Показаны ${info.loaded} из ${info.total} — часть строк не приехала, обновите страницу`
  }
  if (info.filtered) return `Показано ${info.matched} из ${info.total}`
  return `Всего: ${info.total}`
}

// ─── Адрес страницы ──────────────────────────────────────────────────────────

const BUCKET_KEYS = new Set<string>(PROGRESS_BUCKETS.map((b) => b.key))
const SORT_KEYS = new Set<string>(PROGRESS_SORTS.map((s) => s.key))

export function resolveProgressFilters(params: URLSearchParams): ProgressFilters {
  const bucket = params.get('bucket')
  return {
    q: params.get('q') ?? '',
    storeId: params.get('store'),
    positionId: params.get('pos'),
    linkedOnly: params.get('acct') === '1',
    bucket: bucket && BUCKET_KEYS.has(bucket) ? (bucket as ProgressBucket) : null,
  }
}

export function resolveProgressSort(params: URLSearchParams): ProgressSort {
  const sort = params.get('sort')
  return sort && SORT_KEYS.has(sort) ? (sort as ProgressSort) : 'lagging'
}

/**
 * Пишет только свои ключи и НИКОГДА не трогает `tab`.
 *
 * `LearnAdminPage` в эффекте переписывает `?tab=` из захваченного значения:
 * если дочерний экран отдаст новый объект без `tab`, вкладка отскочит на
 * первую доступную. Тот же класс ошибки уже разобран в `myTasksTabs.ts`.
 */
export function setProgressParams(
  params: URLSearchParams,
  patch: Partial<ProgressFilters & { sort: ProgressSort }>,
): URLSearchParams {
  const next = new URLSearchParams(params)
  const put = (key: string, value: string | null, isDefault: boolean) => {
    if (value === null || value === '' || isDefault) next.delete(key)
    else next.set(key, value)
  }
  if ('q' in patch) put('q', patch.q ?? '', (patch.q ?? '') === '')
  if ('storeId' in patch) put('store', patch.storeId ?? null, false)
  if ('positionId' in patch) put('pos', patch.positionId ?? null, false)
  if ('linkedOnly' in patch) put('acct', patch.linkedOnly ? '1' : null, false)
  if ('bucket' in patch) put('bucket', patch.bucket ?? null, false)
  if ('sort' in patch) put('sort', patch.sort ?? null, patch.sort === 'lagging')
  return next
}

export function clearProgressParams(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params)
  for (const key of ['q', 'store', 'pos', 'acct', 'bucket']) next.delete(key)
  return next
}
