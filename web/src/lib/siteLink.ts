/** Связь магазина с объектом реестра auth (0053, выкат 3).
 *
 *  Правила чистые и живут здесь, а не в JSX: состояний ТРИ, и третье в
 *  разметке сгнило бы молча — протухший ключ (403 у нас тихий INFO) давал бы
 *  пустой адрес там, где раньше был локальный, без единого сигнала.
 */

import type { OrgStore, SiteMirror } from '@/lib/learn'

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
