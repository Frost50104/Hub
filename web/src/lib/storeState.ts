/** Состояние точки для пикеров (0065, 19.10).
 *
 *  У точки две оси, и обе пришли из реестра auth: `archived_at` — закрыта
 *  навсегда (карточка архивируется), `suspended_at` — ВРЕМЕННО не работает
 *  (ремонт, сезон, пауза; карточка живая, метку снимает реестр). Контракт один
 *  на обе: новое на такую точку не назначается — ни людей, ни смен, ни правил
 *  аудиторий. Уже выбранное значение формы показывается всё равно, с подписью:
 *  это решает вызывающий (`storeAssignable(s) || s.id === current`), иначе
 *  поле выглядело бы пустым и его перезаписали бы, не заметив.
 *
 *  Фильтры отчётов («Прогресс по точке») сюда не относятся: смотреть данные
 *  приостановленной точки можно, назначать на неё — нет.
 */

import type { OrgStore } from '@/lib/learn'

type StoreState = Pick<OrgStore, 'archived_at'> & { suspended_at?: string | null }

export function storeAssignable(s: StoreState): boolean {
  return !s.archived_at && !s.suspended_at
}

/** Подпись точки там, где она уже выбрана; архив важнее паузы. */
export function storeLabel(s: StoreState & Pick<OrgStore, 'name'>): string {
  if (s.archived_at) return `${s.name} (архив)`
  if (s.suspended_at) return `${s.name} (приостановлена)`
  return s.name
}
