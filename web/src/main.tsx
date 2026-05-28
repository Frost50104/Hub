import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'
import { Toaster } from './components/ui/Toaster'
import { UpdateBanner } from './components/UpdateBanner'
import { queryClient } from './lib/queryClient'
import './styles/globals.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root element missing in index.html')

createRoot(root).render(
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
