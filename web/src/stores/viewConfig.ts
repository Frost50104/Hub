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
      version: 1,
    },
  ),
)
