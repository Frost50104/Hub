import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ProjectViewConfig {
  /** Custom-field IDs that should appear as columns in the List view.
   *  Order = render order; absence = hidden. */
  visibleCustomFields: string[]
  /** Свёрнутые секции списка. `'__orphan__'` — блок «Без секции».
   *  Строка выросла до 64px, и сворачивание секций — главное средство
   *  плотности на сотнях задач; в локальном useState оно сбрасывалось при
   *  каждом переключении вкладки вида. */
  collapsedSections?: string[]
}

interface ViewConfigState {
  byProject: Record<string, ProjectViewConfig>
  setVisibleCustomFields: (projectId: string, ids: string[]) => void
  toggleCustomField: (projectId: string, fieldId: string) => void
  getVisible: (projectId: string) => string[]
  toggleSection: (projectId: string, sectionKey: string) => void
}

/** Ключ блока «Без секции» в `collapsedSections`. */
export const ORPHAN_SECTION_KEY = '__orphan__'

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
      toggleSection: (projectId, sectionKey) =>
        set((state) => {
          const cfg = state.byProject[projectId] ?? EMPTY
          const current = cfg.collapsedSections ?? []
          const next = current.includes(sectionKey)
            ? current.filter((k) => k !== sectionKey)
            : [...current, sectionKey]
          return {
            byProject: {
              ...state.byProject,
              [projectId]: { ...cfg, collapsedSections: next },
            },
          }
        }),
    }),
    {
      name: 'hub-view-config',
      // v2: + collapsedSections. Поле опционально, миграция не нужна.
      version: 2,
    },
  ),
)
