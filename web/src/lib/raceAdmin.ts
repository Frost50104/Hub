/**
 * Админка гонки: валидация черновика конкурса (зеркало серверных правил),
 * превью автосгенерированных заездов, пересечение лиг, разбор ввода базы,
 * URL-параметры вкладки. Чистый модуль под vitest.
 */
import type { OrgGroup, OrgStore } from '@/lib/learn'
import type { BaselineMode, RaceContest, RaceRef } from '@/lib/race'
import { addDaysKey, humanDate } from '@/lib/taskDates'
import { plural } from '@/lib/typography'

export interface ContestFormDraft {
  title: string
  starts_on: string
  race_length_days: 7 | 14
  weeks_total: number
  baseline_mode: BaselineMode
  baseline_days: number
  league_group_ids: string[]
}

export function defaultDraft(todayKey: string): ContestFormDraft {
  return {
    title: 'Гусиная гонка',
    starts_on: todayKey,
    race_length_days: 7,
    weeks_total: 4,
    baseline_mode: 'contest',
    baseline_days: 28,
    league_group_ids: [],
  }
}

export function draftFromContest(c: RaceContest, leagueGroupIds: string[]): ContestFormDraft {
  return {
    title: c.title,
    starts_on: c.starts_on,
    race_length_days: c.race_length_days === 14 ? 14 : 7,
    weeks_total: c.weeks_total,
    baseline_mode: c.baseline_mode,
    baseline_days: c.baseline_days,
    league_group_ids: leagueGroupIds,
  }
}

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/

export function contestEndsOn(startsOn: string, weeks: number): string {
  return addDaysKey(startsOn, weeks * 7 - 1)
}

export interface RacePreview {
  seq: number
  starts_on: string
  ends_on: string
}

/** Заезды встык — то, что сгенерирует сервер при «Запланировать». */
export function racesPreview(startsOn: string, weeks: number, len: 7 | 14): RacePreview[] {
  if (!DAY_RE.test(startsOn) || weeks < 1 || (weeks * 7) % len !== 0) return []
  const count = (weeks * 7) / len
  const out: RacePreview[] = []
  let cursor = startsOn
  for (let seq = 1; seq <= count; seq++) {
    const end = addDaysKey(cursor, len - 1)
    out.push({ seq, starts_on: cursor, ends_on: end })
    cursor = addDaysKey(end, 1)
  }
  return out
}

export type DraftErrors = Partial<Record<keyof ContestFormDraft, string>>

export function validateContestDraft(d: ContestFormDraft, todayKey: string, allowPast = false): { ok: boolean; errors: DraftErrors } {
  const errors: DraftErrors = {}
  if (!d.title.trim()) errors.title = 'Введите название'
  else if (d.title.trim().length > 120) errors.title = 'Не длиннее 120 символов'
  if (!DAY_RE.test(d.starts_on)) errors.starts_on = 'Укажите дату старта'
  else if (!allowPast && d.starts_on < todayKey) errors.starts_on = 'Дата старта уже прошла'
  if (d.race_length_days !== 7 && d.race_length_days !== 14) errors.race_length_days = 'Длина заезда — 7 или 14 дней'
  if (!Number.isInteger(d.weeks_total) || d.weeks_total < 1 || d.weeks_total > 12) errors.weeks_total = 'От 1 до 12 недель'
  else if ((d.weeks_total * 7) % d.race_length_days !== 0) errors.weeks_total = 'Число недель должно делиться на длину заезда'
  if (!Number.isInteger(d.baseline_days) || d.baseline_days < 7 || d.baseline_days > 92) errors.baseline_days = 'От 7 до 92 дней'
  return { ok: Object.keys(errors).length === 0, errors }
}

export interface LeagueOverlap {
  storeId: string
  name: string
  groupNames: string[]
}

/** Точка в двух выбранных группах — сервер ответит 422; архивные не считаем. */
export function leagueOverlaps(selectedIds: string[], groups: OrgGroup[], stores: OrgStore[]): LeagueOverlap[] {
  const live = new Map(stores.filter((s) => !s.archived_at).map((s) => [s.id, s.name] as const))
  const byStore = new Map<string, string[]>()
  for (const g of groups) {
    if (!selectedIds.includes(g.id)) continue
    for (const sid of g.member_ids) {
      if (!live.has(sid)) continue
      byStore.set(sid, [...(byStore.get(sid) ?? []), g.name])
    }
  }
  return [...byStore.entries()]
    .filter(([, names]) => names.length > 1)
    .map(([storeId, groupNames]) => ({ storeId, name: live.get(storeId) ?? '?', groupNames }))
    .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
}

/** Новый конкурс нельзя завести, пока есть черновик, запланированный или активный. */
export function canCreateContest(contests: Pick<RaceContest, 'status'>[]): boolean {
  return !contests.some((c) => c.status === 'draft' || c.status === 'scheduled' || c.status === 'active')
}

export function parseBaselineInput(raw: string): { value: number } | { error: string } {
  const s = raw.trim().replace(',', '.')
  if (!s) return { error: 'Введите число' }
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return { error: 'Число с двумя знаками, например 2,35' }
  const value = Number(s)
  if (!(value > 0)) return { error: 'База должна быть больше нуля' }
  if (value > 50) return { error: 'Слишком большое значение' }
  return { value }
}

export const CONTEST_STATUS_LABEL: Record<RaceContest['status'], string> = {
  draft: 'черновик',
  scheduled: 'запланирован',
  active: 'идёт',
  finished: 'завершён',
  cancelled: 'отменён',
}

export const RACE_STATUS_LABEL: Record<'scheduled' | 'active' | 'finished', string> = {
  scheduled: 'не начат',
  active: 'идёт',
  finished: 'завершён',
}

export interface RaceAdminParams {
  contest: string | null
  brace: string | null
}

export function resolveRaceAdminParams(params: URLSearchParams): RaceAdminParams {
  return { contest: params.get('contest'), brace: params.get('brace') }
}

/** Свои ключи и только они — `tab` не трогаем (LearnAdminPage отбросит на первую вкладку). */
export function setRaceAdminParams(params: URLSearchParams, patch: Partial<RaceAdminParams>): URLSearchParams {
  const next = new URLSearchParams(params)
  for (const key of ['contest', 'brace'] as const) {
    if (!(key in patch)) continue
    const v = patch[key]
    if (v) next.set(key, v)
    else next.delete(key)
  }
  return next
}

// ─── ранний старт заезда ─────────────────────────────────────────────────────

/** Подпись кнопки: сервер уже решил, что заезд можно начать раньше и с какого дня. */
export function earlyStartLabel(earlyStartOn: string, todayKey: string): string {
  if (earlyStartOn === todayKey) return 'Начать сегодня'
  if (earlyStartOn === addDaysKey(todayKey, 1)) return 'Начать завтра'
  return `Начать ${humanDate(earlyStartOn)}`
}

function raceDays(startsOn: string, endsOn: string): number {
  const a = new Date(`${startsOn}T00:00:00Z`).getTime()
  const b = new Date(`${endsOn}T00:00:00Z`).getTime()
  return Math.round((b - a) / 86_400_000) + 1
}

/**
 * Текст подтверждения раннего старта: новая дата, неизменное окончание,
 * длина заезда против плановой; в режиме «база на каждый заезд» при старте
 * «сегодня» — предупреждение о походе в iiko (при «завтра» базу посчитает
 * ночная джоба, человеку об этом знать не нужно).
 */
export function earlyStartText(
  race: Pick<RaceRef, 'seq' | 'starts_on' | 'ends_on'>,
  earlyStartOn: string,
  contest: Pick<RaceContest, 'race_length_days' | 'baseline_mode' | 'baseline_days'>,
  todayKey: string,
): string {
  const when = earlyStartOn === todayKey ? 'сегодня' : earlyStartOn === addDaysKey(todayKey, 1) ? 'завтра' : humanDate(earlyStartOn)
  const days = raceDays(earlyStartOn, race.ends_on)
  const parts = [
    `Заезд № ${race.seq} стартует ${when} вместо ${humanDate(race.starts_on)}.`,
    `Окончание не меняется — ${humanDate(race.ends_on)}: заезд продлится ${plural(days, 'день', 'дня', 'дней')} вместо ${contest.race_length_days}.`,
  ]
  if (contest.baseline_mode === 'race' && earlyStartOn === todayKey) {
    parts.push(`База пересчитается из iiko за ${plural(contest.baseline_days, 'день', 'дня', 'дней')} до старта.`)
  }
  return parts.join(' ')
}

/** «· 10 дней вместо 7» — заезд длиннее плана (стартовал раньше); иначе null. */
export function raceLengthNote(race: Pick<RaceRef, 'starts_on' | 'ends_on'>, raceLengthDays: number): string | null {
  const days = raceDays(race.starts_on, race.ends_on)
  if (days === raceLengthDays) return null
  return `· ${plural(days, 'день', 'дня', 'дней')} вместо ${raceLengthDays}`
}
