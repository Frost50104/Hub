import { createPortal } from 'react-dom'
import { Toaster as SonnerToaster } from 'sonner'

import { useTheme } from '@/lib/theme'

/**
 * Тостер живёт ПОРТАЛОМ в `body`, а не там, где стоит в дереве.
 *
 * Без этого его не видно из-под карточки задачи, и никакой z-index не
 * помогает: `#root` — стекинг-контекст (`position:relative; z-index:1` в
 * `styles/brand.css`, поднимает приложение над dot-grid'ом `body::before`).
 * Всё внутри него, включая `z-index: 999999999` самого sonner, прижато к
 * уровню 1, а карточка задачи уезжает порталом Radix прямо в `body` со своим
 * `z-index: 40` — и 40 в корневом контексте всегда больше единицы. Тост
 * оказывался ПОД карточкой (и под мобильным листом, z-50).
 *
 * В `body` его собственный z-index наконец с чем сравнивать.
 */
export function Toaster() {
  const theme = useTheme((s) => s.theme)
  return createPortal(
    <SonnerToaster
      // Сверху, а не снизу: на мобильном sonner растягивает тост на всю
      // ширину и он садился ровно на таб-бар, перекрывая основную
      // навигацию (ОС 19.08).
      //
      // По центру, а не справа: у правого края живёт карточка задачи —
      // непрозрачная панель 560px (TaskDetailDrawer), и тост ложился ровно
      // на её ключ, колокол, «…» и крестик, держа их закрытыми все четыре
      // секунды. Прятал он, а не его: у контейнера sonner z-index
      // 999999999, он выше и панели (z-40), и мобильного листа (z-50).
      // По центру перекрывается максимум заголовок страницы.
      position="top-center"
      theme={theme}
      // Только top: при центрировании горизонтальный отступ ни на что не
      // влияет, а в коде выглядел бы работающим.
      offset={{ top: '1rem' }}
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
    />,
    document.body,
  )
}
