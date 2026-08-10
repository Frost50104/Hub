import * as DialogPrimitive from '@radix-ui/react-dialog'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'

/**
 * Полноэкранный просмотр картинок урока. Raw DialogPrimitive, а не ui/Dialog:
 * той обёртке прошита glass-карточка max-w-lg — для лайтбокса нужен голый
 * фуллскрин. Esc / тап по фону закрывают (Radix), тап по самой картинке —
 * нет (stopPropagation). Зума нет — осознанное ограничение (PWA-viewport +
 * scroll-lock Radix ломают pinch), картинка растягивается object-contain.
 */

export interface LightboxImage {
  src: string
  caption?: string
}

export function ImageLightbox({
  images,
  index,
  onIndexChange,
  open,
  onOpenChange,
}: {
  images: LightboxImage[]
  index: number
  onIndexChange: (i: number) => void
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const img = images[index]
  if (!img) return null

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/90" />
        <DialogPrimitive.Content
          className="fixed inset-0 z-50 flex flex-col items-center justify-center outline-none"
          onClick={() => onOpenChange(false)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight' && index < images.length - 1) onIndexChange(index + 1)
            if (e.key === 'ArrowLeft' && index > 0) onIndexChange(index - 1)
          }}
        >
          <DialogPrimitive.Title className="sr-only">
            Просмотр изображения
          </DialogPrimitive.Title>

          <img
            src={img.src}
            alt={img.caption || 'Изображение'}
            className="max-h-[88vh] max-w-[96vw] object-contain"
            onClick={(e) => e.stopPropagation()}
          />
          {img.caption && (
            <p
              className="mt-2 max-w-[90vw] text-center text-sm text-white/80"
              onClick={(e) => e.stopPropagation()}
            >
              {img.caption}
            </p>
          )}

          {/* Крестик — под iOS-чёлкой в PWA без safe-area уехал бы за экран. */}
          <DialogPrimitive.Close
            aria-label="Закрыть"
            onClick={(e) => e.stopPropagation()}
            className="absolute right-3 z-10 rounded-full bg-black/60 p-2.5 text-white transition-colors hover:bg-black/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            style={{ top: 'calc(env(safe-area-inset-top, 0px) + 0.75rem)' }}
          >
            <X className="h-5 w-5" />
          </DialogPrimitive.Close>

          {images.length > 1 && (
            <>
              {index > 0 && (
                <button
                  type="button"
                  aria-label="Предыдущее"
                  onClick={(e) => {
                    e.stopPropagation()
                    onIndexChange(index - 1)
                  }}
                  className="absolute left-2 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-black/60 text-white hover:bg-black/80"
                >
                  <ChevronLeft className="h-6 w-6" />
                </button>
              )}
              {index < images.length - 1 && (
                <button
                  type="button"
                  aria-label="Следующее"
                  onClick={(e) => {
                    e.stopPropagation()
                    onIndexChange(index + 1)
                  }}
                  className="absolute right-2 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-black/60 text-white hover:bg-black/80"
                >
                  <ChevronRight className="h-6 w-6" />
                </button>
              )}
              <span
                className="absolute rounded-full bg-black/60 px-3 py-1 text-xs text-white/90"
                style={{ bottom: 'calc(env(safe-area-inset-bottom, 0px) + 1rem)' }}
                onClick={(e) => e.stopPropagation()}
              >
                {index + 1} из {images.length}
              </span>
            </>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
