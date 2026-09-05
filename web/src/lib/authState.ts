/** Статус учётки на экране «Сотрудники» (staff-sync, 0052).
 *
 *  Сам статус считает БЭКЕНД (`employees.py::auth_state_for` — одна правда
 *  вместо двух рассинхронённых признаков в JSX); здесь — только словарь
 *  отображения и порядок фильтров. Чистый модуль ради vitest.
 */

export type AuthState =
  | 'no_account'
  | 'not_linked' // до первого синка «без учётки» утверждать нельзя — только «не привязан»
  | 'not_logged_in'
  | 'active'
  | 'blocked'
  | 'deleted'

export const AUTH_STATE_LABEL: Record<AuthState, string> = {
  no_account: 'Без учётки',
  not_linked: 'Не привязан(а)',
  not_logged_in: 'Не входил(а)',
  active: 'Активен',
  blocked: 'Заблокирован(а) в auth',
  deleted: 'Удалён(а) в auth',
}

/** Тон бейджа: amber = требует внимания, red = доступ закрыт, без тона = норма. */
export function authStateTone(state: AuthState): 'amber' | 'red' | null {
  if (state === 'no_account' || state === 'not_linked' || state === 'not_logged_in') return 'amber'
  if (state === 'blocked' || state === 'deleted') return 'red'
  return null
}

export const HUB_ROLE_LABEL: Record<string, string> = {
  admin: 'Админ',
  member: 'Участник',
  viewer: 'Наблюдатель',
}

/** «Активен» не бейджим — иначе список на 260 строк превращается в радугу. */
export function showAuthStateBadge(state: AuthState | null | undefined): state is AuthState {
  return !!state && state !== 'active'
}

export interface StaffSyncToastInput {
  available: boolean
  dry_run: boolean
  profiles_created: number
  profiles_linked: number
  email_conflicts: number
}

/** Текст тоста кнопки «Обновить из auth». Dry-run сервер форсит, пока
 *  staff-sync выключен: числа честные («создал бы»), но записи не было —
 *  говорить «Синхронизировано» в этом состоянии значит врать админу. */
export function staffSyncToast(r: StaffSyncToastInput): {
  kind: 'message' | 'success'
  text: string
} {
  if (!r.available) {
    return { kind: 'message', text: 'Auth не отдаёт список штата — синхронизация пока недоступна' }
  }
  const tail = r.email_conflicts ? `, конфликтов email: ${r.email_conflicts}` : ''
  if (r.dry_run) {
    return {
      kind: 'message',
      text:
        `Подсчёт без записи (синхронизация выключена): будет создано карточек ${r.profiles_created}, ` +
        `привязано ${r.profiles_linked}${tail}`,
    }
  }
  return {
    kind: 'success',
    text: `Синхронизировано: карточек создано ${r.profiles_created}, привязано ${r.profiles_linked}${tail}`,
  }
}
