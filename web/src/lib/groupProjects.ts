import { type ProjectFolder } from './projectFolders'
import { type Project } from './projects'

/** id дропзоны и группы для проектов вне папок. */
export const UNFILED = '__unfiled__'

export interface ProjectGroup {
  /** null — группа «Без папки». */
  folder: ProjectFolder | null
  projects: Project[]
}

/**
 * Разложить проекты по папкам.
 *
 * Правила (каждое — из потенциального бага):
 * 1. Папок нет → одна безымянная группа. Тенанты, которые папками не
 *    пользуются, не должны увидеть ни одного нового заголовка.
 * 2. Порядок групп = порядок с сервера (он уже отсортирован), «Без папки» —
 *    последней.
 * 3. Проект со ссылкой на УДАЛЁННУЮ папку (другой пользователь удалил, кэш
 *    устарел) попадает в «Без папки», а не теряется — иначе это баг-репорт
 *    «мой проект пропал».
 * 4. Пустые папки сохраняются: они нужны как drop-зоны. Прятать их —
 *    решение вызывающего (сайдбар прячет, страница нет).
 * 5. Внутри группы — по имени с русской локалью: серверный порядок
 *    (created_at desc) для «картотеки» бессмысленен.
 *
 * Отдельный модуль от `projectFolders.ts`: тот тянет `api` → `auth` →
 * `window`, а vitest в проекте бежит без jsdom.
 */
export function groupProjectsByFolder(
  projects: Project[],
  folders: ProjectFolder[],
): ProjectGroup[] {
  const byName = (a: Project, b: Project) => a.name.localeCompare(b.name, 'ru')

  if (folders.length === 0) {
    return [{ folder: null, projects: [...projects].sort(byName) }]
  }

  const known = new Set(folders.map((f) => f.id))
  const buckets = new Map<string, Project[]>()
  const unfiled: Project[] = []

  for (const p of projects) {
    if (p.folder_id && known.has(p.folder_id)) {
      const list = buckets.get(p.folder_id) ?? []
      list.push(p)
      buckets.set(p.folder_id, list)
    } else {
      unfiled.push(p)
    }
  }

  const groups: ProjectGroup[] = folders.map((folder) => ({
    folder,
    projects: (buckets.get(folder.id) ?? []).sort(byName),
  }))
  groups.push({ folder: null, projects: unfiled.sort(byName) })
  return groups
}
