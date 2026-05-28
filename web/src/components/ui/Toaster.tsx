import { Toaster as SonnerToaster } from 'sonner'

export function Toaster() {
  return (
    <SonnerToaster
      position="bottom-right"
      theme="dark"
      toastOptions={{
        classNames: {
          toast: 'glass !bg-glass !border-glass-border !text-text',
          description: '!text-text2',
          actionButton: '!bg-amber !text-bg',
          cancelButton: '!bg-surface !text-text2',
          error: '!border-red/50',
          success: '!border-green/50',
        },
      }}
    />
  )
}
