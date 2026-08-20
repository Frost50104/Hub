import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'

import { BottomSheet } from '@/components/ui/BottomSheet'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'

interface ResponsiveDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  /** Кнопки. Десктоп — справа за `border-top --hair`; телефон — ряд внизу шторки. */
  footer?: ReactNode
  /** Ширина модалки на десктопе, px. Спека авторского контура: 560. */
  desktopWidth?: number
  /** Подпись правой кнопки шторки (по умолчанию «Отмена»). */
  dismissLabel?: string
  className?: string
  /** Класс области контента (обе раскладки). */
  bodyClassName?: string
}

/**
 * Один диалог на обе раскладки: `<lg` — шторка снизу (ручка 40×4, заголовок
 * по центру, «Отмена» справа, поля 48px), `≥lg` — модалка 560px, радиус 16,
 * футер кнопок справа за `border-top --hair`.
 *
 * Раскладка ФИКСИРУЕТСЯ в момент открытия: `useIsDesktop` реактивен, и
 * поворот планшета посреди заполнения формы иначе размонтировал бы её вместе
 * с введённым. Пока диалог открыт, обёртка не меняется.
 */
export function ResponsiveDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  desktopWidth = 560,
  dismissLabel = 'Отмена',
  className,
  bodyClassName,
}: ResponsiveDialogProps) {
  const isDesktop = useIsDesktop()
  const frozen = useRef<boolean>(isDesktop)
  useEffect(() => {
    if (!open) frozen.current = isDesktop
  }, [open, isDesktop])
  const desktop = open ? frozen.current : isDesktop

  if (!desktop) {
    return (
      <BottomSheet
        open={open}
        onOpenChange={onOpenChange}
        title={title}
        subtitle={description}
        trailing={
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="min-h-11 px-2 text-[15px] font-medium text-text2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 rounded-md"
          >
            {dismissLabel}
          </button>
        }
        className={className}
      >
        <div className={cn('flex flex-col gap-4 px-3 pb-2', bodyClassName)}>{children}</div>
        {footer && (
          <div className="mt-2 flex flex-wrap items-center justify-end gap-2 px-3 pb-2">
            {footer}
          </div>
        )}
      </BottomSheet>
    )
  }

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className={cn(
            // Непрозрачная подложка: в светлой теме стекло просвечивает страницу.
            'fixed left-1/2 top-1/2 z-50 flex max-h-[90vh] w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-2xl border border-glass-border bg-bg-alt shadow-[0_24px_64px_rgba(0,0,0,0.5)] focus:outline-none',
            'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            className,
          )}
          style={{ maxWidth: desktopWidth }}
        >
          <header className="flex items-start gap-3 px-5 pb-3 pt-5">
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title className="font-display text-[17px] font-bold leading-[1.3] text-text">
                {title}
              </DialogPrimitive.Title>
              {description && (
                <DialogPrimitive.Description className="mt-1 text-[14px] leading-[1.45] text-text2">
                  {description}
                </DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close
              aria-label="Закрыть"
              className="-mr-2 -mt-2 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-text2 transition-colors hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            >
              <X className="h-[18px] w-[18px]" />
            </DialogPrimitive.Close>
          </header>
          <div className={cn('flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 pb-5', bodyClassName)}>
            {children}
          </div>
          {footer && (
            <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-hair px-5 pb-5 pt-3.5">
              {footer}
            </footer>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
