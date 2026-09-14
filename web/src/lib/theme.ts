import { create } from 'zustand'

export type Theme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'hub-theme'
/** Чей это кеш. Инлайн-скрипт в index.html его НЕ читает (и не должен: его
 *  тело захешировано в CSP), тег нужен только логике посева в themeSync.ts. */
const OWNER_KEY = 'hub-theme-owner'

/**
 * Theme is applied as an explicit `data-theme` attribute on <html> (default
 * dark). There is no system/auto mode — the stored value is always 'light' or
 * 'dark'.
 *
 * ИСТОЧНИК ИСТИНЫ — СЕРВЕР (`/api/me.theme`, ОС 09.09: на общем устройстве
 * второй вошедший получал тему первого). localStorage понижен до анти-FOUC
 * кеша: инлайн-скрипт в index.html красит страницу до первой отрисовки,
 * `initTheme()` переутверждает кеш на старте бандла, а пришедший ответ `/me`
 * перекрывает и то и другое (`hooks/useThemeSetting.ts`).
 *
 * Модуль намеренно БЕЗ сетевых импортов: он исполняется до рендера и
 * импортируется dev-стендом — axios и queryClient сюда тащить нельзя.
 */
function readStored(): Theme {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch {
    // localStorage unavailable (private mode) — fall through to default.
  }
  return 'dark'
}

/** Сырое чтение: null — ключа НЕТ вовсе (в отличие от `readStored`, который
 *  подменяет отсутствие дефолтом). На различии стоит посев: с дефолтом мы
 *  записали бы на сервер тёмную тему всем, кто её никогда не выбирал. */
export function readStoredRaw(): Theme | null {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch {
    // см. readStored()
  }
  return null
}

export function readThemeOwner(): string | null {
  try {
    return localStorage.getItem(OWNER_KEY)
  } catch {
    return null
  }
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

/**
 * Применить тему локально: DOM + стор + кеш (+ тег владельца, если знаем).
 *
 * Через СТОР, а не только `applyTheme`: от `useTheme` зависят бренд-ассет в
 * сайдбарах (на светлой нужен on-light логотип) и проп `theme` у sonner —
 * покраска одного `data-theme` даёт светлую тему с тёмным логотипом.
 */
export function setThemeLocal(theme: Theme, employeeId?: string): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
    if (employeeId) localStorage.setItem(OWNER_KEY, employeeId)
  } catch {
    // ignore persistence failures — the in-memory choice still applies.
  }
  applyTheme(theme)
  useTheme.setState({ theme })
}

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
}

export const useTheme = create<ThemeState>(() => ({
  theme: readStored(),
  // Единственный писатель кеша и DOM — `setThemeLocal`: две копии этой логики
  // разъезжаются молча (одна пишет тег владельца, другая нет).
  setTheme: (theme) => setThemeLocal(theme),
}))
