import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { forwardRef, useState, type ComponentPropsWithoutRef, type ElementRef } from 'react'

import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close
export const DialogPortal = DialogPrimitive.Portal

export const DialogOverlay = forwardRef<
  ElementRef<typeof DialogPrimitive.Overlay>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      'fixed inset-0 z-50 bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
      className,
    )}
    {...props}
  />
))
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName

const MODAL_CLASS =
  'glass-solid fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 p-6 shadow-glass focus:outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95'

// Ниже lg тот же диалог — ШТОРКА снизу (редизайн-2, макеты авторского
// контура и мобильных пикеров): ручка 40×4, скруглённый верх, прокрутка
// внутри. Раскладка фиксируется при монтировании контента (= открытии):
// поворот планшета посреди формы не должен пересобирать её.
const SHEET_CLASS =
  'glass-solid fixed inset-x-0 bottom-0 z-50 mx-auto max-h-[88vh] w-full overflow-y-auto rounded-t-2xl p-5 pt-2 shadow-glass focus:outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom'

export const DialogContent = forwardRef<
  ElementRef<typeof DialogPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, style, ...props }, ref) => {
  const isDesktop = useIsDesktop()
  const [sheet] = useState(() => !isDesktop)
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(sheet ? SHEET_CLASS : MODAL_CLASS, className)}
        style={
          sheet
            ? { paddingBottom: 'max(env(safe-area-inset-bottom, 0px), 20px)', ...style }
            : style
        }
        {...props}
      >
        {sheet && (
          <div className="mb-2 flex justify-center">
            <span className="h-1 w-10 rounded-full bg-text3/40" aria-hidden />
          </div>
        )}
        {children}
        <DialogPrimitive.Close
          className={cn(
            'absolute right-4 rounded-sm p-1 text-text3 transition-colors hover:text-text focus:outline-none focus:ring-1 focus:ring-amber',
            sheet ? 'top-3 h-9 w-9 p-2' : 'top-4',
          )}
        >
          <X className="h-4 w-4" />
          <span className="sr-only">Закрыть</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPortal>
  )
})
DialogContent.displayName = DialogPrimitive.Content.displayName

export const DialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn('mb-4 flex flex-col gap-1.5', className)} {...props} />
)

export const DialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn('mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)}
    {...props}
  />
)

export const DialogTitle = forwardRef<
  ElementRef<typeof DialogPrimitive.Title>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn('font-display text-lg font-semibold text-text', className)}
    {...props}
  />
))
DialogTitle.displayName = DialogPrimitive.Title.displayName

export const DialogDescription = forwardRef<
  ElementRef<typeof DialogPrimitive.Description>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn('text-sm text-text2', className)}
    {...props}
  />
))
DialogDescription.displayName = DialogPrimitive.Description.displayName
