import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface FolderCollapseState {
  /** Храним ТОЛЬКО свёрнутые ключи: дефолт — развёрнуто, карта остаётся
   *  крошечной, а «мусор» от удалённых папок — безобидный boolean. */
  collapsed: Record<string, boolean>
  toggle: (folderId: string) => void
  isCollapsed: (folderId: string) => boolean
}

/**
 * Свёрнутость групп папок в сайдбаре и на /projects.
 *
 * Отдельный store, а не `viewConfig.ts`: тот явно per-project (`byProject`),
 * смена его формы потребовала бы бампа persist-version.
 * zustand, а не сырой localStorage: свёрнутость нужна реактивно СРАЗУ в двух
 * поверхностях (сайдбар + страница), сырое чтение не перерендерило бы обе.
 *
 * Состояние общее для обеих поверхностей — осознанное упрощение.
 */
export const useFolderCollapse = create<FolderCollapseState>()(
  persist(
    (set, get) => ({
      collapsed: {},
      toggle: (folderId) =>
        set((state) => ({
          collapsed: { ...state.collapsed, [folderId]: !state.collapsed[folderId] },
        })),
      isCollapsed: (folderId) => get().collapsed[folderId] ?? false,
    }),
    { name: 'hub-project-folders', version: 1 },
  ),
)
