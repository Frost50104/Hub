/**
 * Состояние service worker'а глазами страницы — единый стор, который читают
 * путь кнопки (`lib/appUpdate.ts`), подсказка в Настройках и диагностика.
 *
 * Пишет в него только `lib/serviceWorker.ts`. Zustand-стор при импорте —
 * тот же приём, что `lib/workspace.ts`; в node-тестах читается через
 * `getState()`, без React.
 */

import { create } from 'zustand'

import type { PolledVersion, SwHealth } from './swPolicy'

export interface SwSnapshot {
  /** `navigator.serviceWorker` есть и мы в prod-сборке (в dev воркера нет). */
  supported: boolean
  /** У документа есть контроллер (после hard reload его нет — это нормально). */
  controlled: boolean
  active: boolean
  waiting: boolean
  installing: boolean
}

export interface SwStatusState {
  health: SwHealth
  hungAt: number | null
  probeStartedAt: number | null
  /** Момент СТАРТА последней пробы — шаг между пробами считается от него. */
  lastProbeAt: number | null
  snapshot: SwSnapshot
  /** `getRegistration()` на старте не ответил за потолок — регистрировали заново. */
  lookupTimedOut: boolean
  /** Стартовая чистка HTML из прекеша завершилась (успехом или отказом). */
  purgeSettled: boolean
  /** Версия сервера по последнему опросу баннера; изначально — версия бандла. */
  seenVersion: string
  /** Версия, при которой стартовала последняя проба. */
  probedVersion: string
  polled: PolledVersion | null
  pageLoadedAt: number
  patch: (partial: Partial<Omit<SwStatusState, 'patch'>>) => void
}

export const EMPTY_SNAPSHOT: SwSnapshot = {
  supported: false,
  controlled: false,
  active: false,
  waiting: false,
  installing: false,
}

export function initialSwStatus(loadedVersion: string, now: number): Omit<SwStatusState, 'patch'> {
  return {
    health: 'unknown',
    hungAt: null,
    probeStartedAt: null,
    lastProbeAt: null,
    snapshot: EMPTY_SNAPSHOT,
    lookupTimedOut: false,
    purgeSettled: false,
    seenVersion: loadedVersion,
    probedVersion: loadedVersion,
    polled: null,
    pageLoadedAt: now,
  }
}

export type SwStatusStore = ReturnType<typeof createSwStatusStore>

export function createSwStatusStore(loadedVersion: string, now: number) {
  return create<SwStatusState>((set) => ({
    ...initialSwStatus(loadedVersion, now),
    patch: (partial) => set(partial),
  }))
}

export const useSwStatus = createSwStatusStore(__APP_VERSION__, Date.now())
