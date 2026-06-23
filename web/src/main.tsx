import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'
import { Toaster } from './components/ui/Toaster'
import { UpdateBanner } from './components/UpdateBanner'
import { queryClient } from './lib/queryClient'
import { initSentry } from './lib/sentry'
import { initTheme } from './lib/theme'
import './styles/globals.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root element missing in index.html')

interface BootstrapEnv {
  version?: string
  environment?: string
  sentry_dsn?: string | null
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
        </QueryClientProvider>
      </BrowserRouter>
    </StrictMode>,
  )
}

void bootstrap()
