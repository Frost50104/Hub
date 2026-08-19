import { Toaster as SonnerToaster } from 'sonner'

import { useTheme } from '@/lib/theme'

export function Toaster() {
  const theme = useTheme((s) => s.theme)
  return (
    <SonnerToaster
      // Сверху, а не снизу: на мобильном sonner растягивает тост на всю
      // ширину и он садился ровно на таб-бар, перекрывая основную
      // навигацию (ОС 19.08). Сверху перекрывается максимум заголовок
      // страницы, и то на пару секунд.
      position="top-right"
      theme={theme}
      offset={{ top: '1rem', right: '1rem' }}
      // Мобильные отступы у sonner СВОИ (ниже 600px). Без safe-area тост в
      // PWA на iPhone уехал бы под часы — зеркало той же ошибки, только
      // сверху.
      mobileOffset={{
        top: 'calc(env(safe-area-inset-top, 0px) + 0.75rem)',
        left: '0.75rem',
        right: '0.75rem',
      }}
      toastOptions={{
        classNames: {
          toast: 'glass-solid !border-glass-border !text-text',
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
