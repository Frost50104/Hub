import * as Sentry from '@sentry/react'

let initialized = false

export interface InitSentryOptions {
  dsn: string
  environment: string
  release: string
}

/**
 * Initialise Sentry once, before any React render.
 *
 * Must be called BEFORE `createRoot()` so the SDK captures
 * import-time errors and HTTP failures.
 *
 * Idempotent — safe to call multiple times (e.g. after env-refresh).
 */
export function initSentry({ dsn, environment, release }: InitSentryOptions): void {
  if (initialized) return
  if (!dsn) return
  Sentry.init({
    dsn,
    environment,
    release,
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({
        maskAllText: false,
        blockAllMedia: true,
      }),
    ],
    tracesSampleRate: 0.1,
    replaysOnErrorSampleRate: 1.0,
    replaysSessionSampleRate: 0,
  })
  initialized = true
}

export function identifySentryUser(user: {
  id: string
  email?: string | null
  username?: string | null
}): void {
  if (!initialized) return
  Sentry.setUser({
    id: user.id,
    email: user.email ?? undefined,
    username: user.username ?? undefined,
  })
}

export function clearSentryUser(): void {
  if (!initialized) return
  Sentry.setUser(null)
}

export { Sentry }
