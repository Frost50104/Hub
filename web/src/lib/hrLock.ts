/**
 * Кадровые данные ведутся в auth (шаг 16d, 0063) — что закрыто в Hub и что
 * сказать человеку. Правила считает СЕРВЕР (`OrgSnapshot.hr`,
 * `EmployeeProfile.hr_locked`); здесь — только подписи и работа с формой.
 *
 * Отказ сервера — строкой в `detail` (словарь `extractErrorDetail` не
 * показывает), поэтому распознаём его по началу текста.
 */

import type { EmployeeUpsert, OrgRole } from '@/lib/learn'

export type HrState = 'window' | 'blocked' | 'paused' | 'stale' | 'synced'

export interface HrView {
  frozen: boolean
  window: boolean
  state: HrState | null
  synced_at: string | null
  edit_url: string
  org_url: string
}

/** Поля карточки, которые ведёт auth (ровно блок `hr` контракта). */
export const HR_FIELDS = [
  'hired_at',
  'org_role',
  'position_id',
  'store_id',
  'department_id',
  'franchisee_id',
  'manager_profile_id',
] as const satisfies ReadonlyArray<keyof EmployeeUpsert>

export type HrField = (typeof HR_FIELDS)[number]

export const HR_FIELD_LABEL: Record<HrField | 'tu_stores', string> = {
  hired_at: 'Дата найма',
  org_role: 'Контур',
  position_id: 'Должность',
  store_id: 'Точка',
  department_id: 'Отдел',
  franchisee_id: 'Франчайзи',
  manager_profile_id: 'Руководитель',
  tu_stores: 'Точки ТУ',
}

function hhmm(iso: string): string {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function dayTime(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Строка над кадровым блоком. Главное — сказать ПРАВДУ о том, почему поле
 * неактивно и придут ли правки из auth: заморожено, но не обновляется — самое
 * неприятное состояние, его нельзя маскировать под обычное.
 */
export function hrLineText(view: HrView): { text: string; updated: string | null } {
  switch (view.state) {
    case 'window':
      return { text: 'Идёт перенос кадровых данных в auth — правка временно закрыта', updated: null }
    case 'blocked':
      return {
        text: 'Кадровые данные ведутся в auth. Изменения оттуда ждут подтверждения администратора',
        updated: null,
      }
    case 'paused':
      return {
        text: 'Кадровые данные ведутся в auth. Обновление из auth пока не включено — правки оттуда появятся в Hub позже',
        updated: null,
      }
    case 'stale':
      return {
        text:
          'Кадровые данные ведутся в auth. Hub давно не получал оттуда данные' +
          (view.synced_at ? ` — последний раз ${dayTime(view.synced_at)}` : ''),
        updated: null,
      }
    default:
      return {
        text: 'Кадровые данные ведутся в auth',
        updated: view.synced_at ? `обновлено в ${hhmm(view.synced_at)}` : null,
      }
  }
}

/** Закрытые поля не уходят в запрос вовсе — сервер и так отказал бы на изменение. */
export function omitHrFields<T extends Partial<EmployeeUpsert>>(payload: T): Omit<T, HrField> {
  const out: Partial<T> = { ...payload }
  for (const field of HR_FIELDS) delete out[field as keyof T]
  return out as Omit<T, HrField>
}

const FROZEN_PREFIXES = [
  'Кадровые данные ведутся в auth',
  'Закреплённые точки ведутся в auth',
  'Идёт перенос кадровых данных в auth',
  'Справочник ведётся в auth',
  'Франчайзи точки ведётся в auth',
]

/** Отказ заморозки (422/409): форму надо перечитать — сервер знает больше клиента. */
export function isHrFrozenError(detail: string | null | undefined): boolean {
  return !!detail && FROZEN_PREFIXES.some((p) => detail.startsWith(p))
}

/** Кадровая часть отчёта синка — только числа, без ПДн. */
export interface HrSyncReport {
  mode: 'report' | 'apply' | 'blocked' | 'busy' | 'stale_snapshot' | 'skipped' | 'idle'
  cards?: Partial<Record<'change' | 'fill' | 'skip_linked_empty', string[]>>
  new_cards?: string[]
  valve?: { cards: number; mandatory: number; tripped: boolean }
  applied?: { created: string[]; fields: Record<string, number> }
}

function changedCount(report: HrSyncReport): number {
  return (report.cards?.change?.length ?? 0) + (report.cards?.fill?.length ?? 0)
}

/** Строка про кадровые данные в тосте «Обновить из auth»; null — сказать нечего. */
export function hrSyncToastLine(report: HrSyncReport | null | undefined): string | null {
  if (!report) return null
  const n = changedCount(report)
  const created = report.new_cards?.length ?? 0
  const tail = created ? `, новых карточек ${created}` : ''
  switch (report.mode) {
    case 'report':
      return `Кадровые данные из auth (пробный прогон): изменений карточек ${n}${tail}`
    case 'apply':
      return `Кадровые данные из auth применены: изменено карточек ${n}${tail}`
    case 'blocked':
      return 'Кадровые данные из auth: изменений больше порога — ждут подтверждения администратора'
    case 'busy':
    case 'stale_snapshot':
      return 'Кадровые данные из auth обновляются в фоне — попробуйте через минуту'
    default:
      return null
  }
}

/** Подпись значения в диалоге предохранителя: контур — словами, дата — по-русски. */
export function hrValueLabel(
  field: string,
  value: string | null,
  orgRoleLabel: Record<OrgRole, string>,
): string {
  if (value === null || value === '') return '—'
  if (field === 'org_role') return orgRoleLabel[value as OrgRole] ?? value
  if (field === 'hired_at') {
    const d = new Date(`${value}T00:00:00`)
    return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('ru-RU')
  }
  return value
}

/**
 * Карточку заархивировали по отключению учётки в auth и она держит вход —
 * вернётся сама, когда учётку включат. Кнопка «Восстановить» тут неуместна:
 * сервер откажет, пока учётка отключена.
 */
export function returnsByItself(
  profile: { status: string; archive_reason: string | null; employee_id: string | null },
  view: HrView | null | undefined,
): boolean {
  return (
    !!view?.frozen &&
    profile.status === 'archived' &&
    profile.archive_reason === 'auth_deactivated' &&
    profile.employee_id !== null
  )
}
