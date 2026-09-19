/** Связь магазина с объектом реестра auth (0053, выкат 3).
 *
 *  Правила чистые и живут здесь, а не в JSX: состояний ТРИ, и третье в
 *  разметке сгнило бы молча — протухший ключ (403 у нас тихий INFO) давал бы
 *  пустой адрес там, где раньше был локальный, без единого сигнала.
 */

import type { OrgStore, SiteMirror, SitePending } from '@/lib/learn'

export type SiteLinkState =
  | { kind: 'none' } // site_id нет — локальные поля, как раньше
  | { kind: 'live'; site: SiteMirror } // строка есть и снимок свежий
  | { kind: 'stale' } // связь есть, но строки нет ИЛИ снимок протух

export function siteDisplay(
  store: Pick<OrgStore, 'site_id'>,
  site: SiteMirror | undefined,
  snapshotFresh: boolean,
): SiteLinkState {
  if (!store.site_id) return { kind: 'none' }
  if (!site || !snapshotFresh) return { kind: 'stale' }
  return { kind: 'live', site }
}

export interface DuplicateGroup {
  site_id: string
  stores: OrgStore[]
}

/** Магазины, указывающие на ОДИН объект — артефакт, ради которого реестр
 *  и заводился: дубль перестаёт быть догадкой. Сливать нельзя (пять путей
 *  потери данных — задача auth перечисляет их дословно). */
export function duplicateGroups(stores: OrgStore[]): DuplicateGroup[] {
  const bySite = new Map<string, OrgStore[]>()
  for (const s of stores) {
    if (!s.site_id) continue
    const list = bySite.get(s.site_id)
    if (list) list.push(s)
    else bySite.set(s.site_id, [s])
  }
  return [...bySite.entries()]
    .filter(([, list]) => list.length > 1)
    .map(([site_id, list]) => ({ site_id, stores: list }))
    .sort((a, b) => (a.stores[0]?.name ?? '').localeCompare(b.stores[0]?.name ?? ''))
}

export interface SiteOption {
  value: string
  label: string
  meta?: string
}

/** Варианты для привязки карточки к объекту (19.09): живые объекты, не занятые
 *  другой ЖИВОЙ карточкой, плюс текущий выбор — иначе снять привязку, не
 *  видя её, было бы нельзя. Сервер повторяет проверку (422/409). */
export function sitePickerOptions(
  sites: SiteMirror[],
  stores: Pick<OrgStore, 'id' | 'site_id' | 'archived_at'>[],
  current: { storeId: string | null; siteId: string | null },
): SiteOption[] {
  const taken = new Set(
    stores
      .filter((s) => s.site_id && !s.archived_at && s.id !== current.storeId)
      .map((s) => s.site_id as string),
  )
  return sites
    .filter((s) => s.site_id === current.siteId || (!s.archived_at && !taken.has(s.site_id)))
    .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
    .map((s) => ({
      value: s.site_id,
      label: s.code ? `${s.code} · ${s.name}` : s.name,
      meta: s.address ?? undefined,
    }))
}

/** Почему объект ждёт человека, а не заведён автоматикой. */
export function pendingHint(p: SitePending): string {
  switch (p.reason) {
    case 'no_iiko_ref':
      return 'нет подразделения iiko — строка реестра, не торгующая точка'
    case 'code_collision':
      return `код совпадает с «${p.candidate_store_name ?? 'карточкой без реестра'}» — похоже на неё, привяжите`
    case 'name_collision':
      return `название совпадает с «${p.candidate_store_name ?? 'карточкой без реестра'}» — похоже на неё, привяжите`
  }
}
