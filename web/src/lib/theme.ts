import { create } from 'zustand'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'hub-theme'

/**
 * Theme is applied as an explicit `data-theme` attribute on <html> (default
 * dark). There is no system/auto mode — the stored value is always 'light' or
 * 'dark'.
 *
 * First application happens via an inline script in index.html (before first
 * paint, no FOUC). `initTheme()` re-asserts it once the JS bundle loads so the
 * rendered theme always matches the stored choice (guards against a stale
 * cached document), and `setTheme` handles every change after that.
 */
function readStored(): Theme {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch {
    // localStorage unavailable (private mode) — fall through to default.
  }
  return 'dark'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme)
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', theme === 'light' ? '#ffffff' : '#08080e')
}

/** Re-assert the stored theme on the DOM once React loads (authoritative). */
export function initTheme(): void {
  applyTheme(readStored())
}

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
}

export const useTheme = create<ThemeState>((set) => ({
  theme: readStored(),
  setTheme: (theme) => {
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // ignore persistence failures — the in-memory choice still applies.
    }
    applyTheme(theme)
    set({ theme })
  },
}))
