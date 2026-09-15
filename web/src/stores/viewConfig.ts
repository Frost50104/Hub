import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ProjectViewConfig {
  /** Custom-field IDs that should appear as columns in the List view.
   *  Order = render order; absence = hidden. */
  visibleCustomFields: string[]
}

interface ViewConfigState {
  byProject: Record<string, ProjectViewConfig>
  setVisibleCustomFields: (projectId: string, ids: string[]) => void
  toggleCustomField: (projectId: string, fieldId: string) => void
  getVisible: (projectId: string) => string[]
}

// `collapsedSections` и `toggleSection` сняты 16.09 вместе с секцией «ЛИЧНОЕ»
// на «Моих задачах» — она была их единственным потребителем (секций у списка
// задач нет с 0047/0048). У людей в localStorage останется ключ
// `collapsedSections: ['__personal__']`; он безвреден, но переиспользовать его
// под новую сущность нельзя — у части людей она окажется «уже свёрнутой».

const EMPTY: ProjectViewConfig = { visibleCustomFields: [] }

/**
 * Per-project visibility config for List view custom-field columns.
 *
 * Persisted in localStorage so a refresh keeps the user's column layout.
 * Drawer-only editing keeps the schema small — full inline-edit in the
 * table is a future enhancement (cell-by-cell focus management is XL).
 */
export const useViewConfig = create<ViewConfigState>()(
  persist(
    (set, get) => ({
      byProject: {},
      setVisibleCustomFields: (projectId, ids) =>
        set((state) => ({
          byProject: {
            ...state.byProject,
            [projectId]: { visibleCustomFields: ids },
          },
        })),
      toggleCustomField: (projectId, fieldId) =>
        set((state) => {
          const current = state.byProject[projectId]?.visibleCustomFields ?? []
          const next = current.includes(fieldId)
            ? current.filter((id) => id !== fieldId)
            : [...current, fieldId]
          return {
            byProject: {
              ...state.byProject,
              [projectId]: { visibleCustomFields: next },
            },
          }
        }),
      getVisible: (projectId) =>
        get().byProject[projectId]?.visibleCustomFields ?? EMPTY.visibleCustomFields,
    }),
    {
      name: 'hub-view-config',
      // v2 добавляла collapsedSections; поле снято 16.09, но версию НЕ
      // откатываем: zustand просто смержит незнакомый ключ из localStorage, а
      // понижение версии заставило бы его выбросить и настройки колонок.
      version: 2,
    },
  ),
)
