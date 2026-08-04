import { useLocation } from 'react-router-dom'
import { create } from 'zustand'

/**
 * Два пространства Hub: «Задачи» (таск-трекер) и «Обучение» (LMS).
 *
 * Активное пространство ВЫВОДИТСЯ из URL (`/learn/*` → learn), нейтральные
 * роуты (/inbox и т.п.) наследуют последнее посещённое — см. `resolveSpace`.
 * Тут хранится только «последнее посещённое» для нейтральных роутов и
 * восстановления пространства при холодном старте.
 */

export type Space = 'tasks' | 'learn'

const STORAGE_KEY = 'hub-space'

/** Прямая классификация URL. Для активного пространства используй
 * `resolveSpace`/`useResolvedSpace` — они учитывают нейтральные роуты. */
export function spaceFromPath(pathname: string): Space {
  return pathname === '/learn' || pathname.startsWith('/learn/') ? 'learn' : 'tasks'
}

/** Роуты, общие для обоих пространств — не переключают и не запоминают space. */
const NEUTRAL_PATHS = ['/inbox', '/search', '/profile', '/settings'] as const

export function isNeutralPath(pathname: string): boolean {
  return NEUTRAL_PATHS.some((p) => pathname === p || pathname.startsWith(p + '/'))
}

/** Активное пространство: /learn* → learn; нейтральные роуты → последнее
 * посещённое; всё остальное → tasks. */
export function resolveSpace(pathname: string, lastSpace: Space): Space {
  if (spaceFromPath(pathname) === 'learn') return 'learn'
  if (isNeutralPath(pathname)) return lastSpace
  return 'tasks'
}

/** true ровно один раз за загрузку приложения (module-level: переживает
 * StrictMode double-effect и ре-рендеры, сбрасывается только full reload'ом).
 * Потребитель — boot-redirect в Shell: вернуть пользователя в learn при
 * холодном старте на "/", не отбирая явный клик «Задачи» в переключателе. */
let bootRedirectConsumed = false
export function consumeBootSpaceRedirect(): boolean {
  if (bootRedirectConsumed) return false
  bootRedirectConsumed = true
  return true
}

function readStored(): Space {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'tasks' || v === 'learn') return v
  } catch {
    // private mode — ок, дефолт
  }
  return 'tasks'
}

interface WorkspaceState {
  lastSpace: Space
  rememberSpace: (space: Space) => void
}

export const useWorkspace = create<WorkspaceState>((set) => ({
  lastSpace: readStored(),
  rememberSpace: (space) => {
    try {
      localStorage.setItem(STORAGE_KEY, space)
    } catch {
      // ignore
    }
    set({ lastSpace: space })
  },
}))

export function useResolvedSpace(): Space {
  const { pathname } = useLocation()
  const lastSpace = useWorkspace((s) => s.lastSpace)
  return resolveSpace(pathname, lastSpace)
}
