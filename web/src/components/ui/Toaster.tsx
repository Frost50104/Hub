import { Toaster as SonnerToaster } from 'sonner'

import { useTheme } from '@/lib/theme'

export function Toaster() {
  const theme = useTheme((s) => s.theme)
  return (
    <SonnerToaster
      position="bottom-right"
      theme={theme}
      toastOptions={{
        classNames: {
          toast: 'glass !bg-glass !border-glass-border !text-text',
          description: '!text-text2',
          actionButton: '!bg-amber !text-on-amber',
          cancelButton: '!bg-surface !text-text2',
          error: '!border-red/50',
          success: '!border-green/50',
        },
      }}
    />
  )
}
