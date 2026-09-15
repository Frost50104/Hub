import { describe, expect, it } from 'vitest'

import {
  parseReloadStamp,
  RELOAD_WINDOW_MS,
  shouldReloadOnPreloadError,
} from './preloadRecovery'

const NOW = 1_700_000_000_000

describe('shouldReloadOnPreloadError', () => {
  it('первый провал чанка лечится перезагрузкой', () => {
    expect(shouldReloadOnPreloadError(null, NOW, true)).toBe(true)
  })

  it('повторный провал в течение минуты — НЕ перезагрузка', () => {
    // Если падает и свежий бандл, это настоящий баг: бесконечный reload
    // спрятал бы даже экран ошибки.
    expect(shouldReloadOnPreloadError(NOW - 5_000, NOW, true)).toBe(false)
  })

  it('после окна снова можно: следующий деплой — следующий протухший кеш', () => {
    expect(shouldReloadOnPreloadError(NOW - RELOAD_WINDOW_MS, NOW, true)).toBe(true)
  })

  it('офлайн не перезагружаемся НИКОГДА', () => {
    // `vite:preloadError` прилетает и от обычной потери связи. Перезагрузка
    // там ничего не чинит — страница за ней тоже не загрузится, — а
    // несохранённую работу стирает (ОС 16.09).
    expect(shouldReloadOnPreloadError(null, NOW, false)).toBe(false)
    expect(shouldReloadOnPreloadError(NOW - RELOAD_WINDOW_MS, NOW, false)).toBe(false)
  })
})

describe('parseReloadStamp', () => {
  it('мусор и пусто читаются как «не перезагружались»', () => {
    expect(parseReloadStamp(null)).toBeNull()
    expect(parseReloadStamp('вчера')).toBeNull()
    expect(parseReloadStamp('-5')).toBeNull()
  })

  it('число читается как есть', () => {
    expect(parseReloadStamp(String(NOW))).toBe(NOW)
  })
})
