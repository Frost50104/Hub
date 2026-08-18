import { UNFILED } from './groupProjects'

export const FOLDER_DROP_PREFIX = 'folder-'

/** Полезная нагрузка draggable'а. Страница и сайдбар обязаны класть одно и то
 *  же — на этом держится общий `resolveFolderMove`. */
export interface ProjectDragData {
  projectId: string
  folderId: string | null
}

/** dnd-id дропзоны папки; null — группа «Без папки». */
export function folderDropId(folderId: string | null): string {
  return FOLDER_DROP_PREFIX + (folderId ?? UNFILED)
}

/** null — id не наш (дропнули мимо зоны). */
export function parseFolderDropId(id: string): { folderId: string | null } | null {
  if (!id.startsWith(FOLDER_DROP_PREFIX)) return null
  const raw = id.slice(FOLDER_DROP_PREFIX.length)
  return { folderId: raw === UNFILED ? null : raw }
}

/**
 * dnd-id перетаскиваемого проекта.
 *
 * `scope` нужен ТОЛЬКО сайдбару: там один проект рендерится дважды — в
 * «Избранном» и в своей папке. Без префикса вторая регистрация в
 * `draggableNodes` перетёрла бы первую, обе строки считали бы себя
 * перетаскиваемыми (`isDragging` = `active.id === id`), а `folderId` пришёл бы
 * от смонтированного последним. Симптом плавающий: «иногда переносит не тот».
 */
export function projectDragId(scope: 'fav' | 'group', projectId: string): string {
  return `${scope}:${projectId}`
}

/**
 * Единственное место, где решается, нужен ли запрос на перенос.
 * null — дропнули мимо зоны или в ту же папку, где проект уже лежит.
 */
export function resolveFolderMove(
  data: ProjectDragData | undefined,
  overId: string | number | undefined,
): { projectId: string; folderId: string | null } | null {
  if (!data || overId == null) return null
  const target = parseFolderDropId(String(overId))
  if (!target) return null
  if (data.folderId === target.folderId) return null
  return { projectId: data.projectId, folderId: target.folderId }
}
