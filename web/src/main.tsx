import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'
import { EnvChip } from './components/EnvChip'
import { Toaster } from './components/ui/Toaster'
import { UpdateBanner } from './components/UpdateBanner'
import { setBackendEnv } from './lib/appEnv'
import { queryClient } from './lib/queryClient'
import { initSentry } from './lib/sentry'
import { setDisplayTz } from './lib/taskDates'
import { initTheme } from './lib/theme'
import './styles/globals.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root element missing in index.html')

interface BootstrapEnv {
  version?: string
  environment?: string
  sentry_dsn?: string | null
  display_timezone?: string
}

async function bootstrap(): Promise<void> {
  // Re-assert the persisted theme as soon as the bundle runs — keeps the
  // rendered theme in sync with the toggle even if a cached document loaded.
  initTheme()
  // Fetch /api/env BEFORE first render so Sentry captures import-time errors.
  // /api/env is public (no auth) — bare fetch keeps Sentry init independent
  // of the axios+attachAxiosAuth pipeline.
  try {
    const res = await fetch('/api/env', { credentials: 'omit' })
    if (res.ok) {
      const env = (await res.json()) as BootstrapEnv
      // ДО проверки на sentry_dsn: маркер окружения нужен независимо от того,
      // заведён ли Sentry (а он пока выключен на обоих env).
      setBackendEnv(env.environment)
      // Срок задачи = календарный день в этой зоне (lib/taskDates).
      setDisplayTz(env.display_timezone)
      if (env.sentry_dsn) {
        initSentry({
          dsn: env.sentry_dsn,
          environment: env.environment ?? 'unknown',
          release: env.version ?? 'unknown',
        })
      }
    }
  } catch {
    // /api/env unreachable on first paint — render anyway, retries via TanStack.
  }

  createRoot(root!).render(
    <StrictMode>
      <BrowserRouter>
        <QueryClientProvider client={queryClient}>
          <App />
          <Toaster />
          <UpdateBanner />
          <EnvChip />
        </QueryClientProvider>
      </BrowserRouter>
    </StrictMode>,
  )
}

void bootstrap()
