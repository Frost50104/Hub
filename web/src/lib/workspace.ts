import { create } from 'zustand'

/**
 * Два пространства Hub: «Задачи» (таск-трекер) и «Обучение» (LMS).
 *
 * Активное пространство ВЫВОДИТСЯ из URL (`/learn/*` → learn) — тут хранится
 * только «последнее посещённое» для редиректа после логина и для кнопки
 * переключателя. Никакого дублирующего состояния.
 */

export type Space = 'tasks' | 'learn'

const STORAGE_KEY = 'hub-space'

export function spaceFromPath(pathname: string): Space {
  return pathname === '/learn' || pathname.startsWith('/learn/') ? 'learn' : 'tasks'
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
