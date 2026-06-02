import * as DialogPrimitive from '@radix-ui/react-dialog'
import { forwardRef, type ReactNode } from 'react'

import { cn } from '@/lib/cn'

interface BottomSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Title shown centered in the sheet header. */
  title?: ReactNode
  /** Optional secondary line under the title. */
  subtitle?: ReactNode
  /** Trailing action in the header — typically a "Done"/"Сбросить" link. */
  trailing?: ReactNode
  children: ReactNode
  className?: string
}

/**
 * Asana-style bottom sheet (iOS modal half-sheet). Slides in from the
 * bottom, rounded top corners, draggable visual handle (decorative —
 * tap-outside / overlay dismisses). Caps at 85vh and scrolls internally.
 */
export const BottomSheet = forwardRef<HTMLDivElement, BottomSheetProps>(
  function BottomSheet(
    { open, onOpenChange, title, subtitle, trailing, children, className },
    ref,
  ) {
    return (
      <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay
            className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
          />
          <DialogPrimitive.Content
            ref={ref}
            className={cn(
              'fixed inset-x-0 bottom-0 z-50 max-h-[85vh] overflow-y-auto rounded-t-2xl bg-bg-alt shadow-glass focus:outline-none',
              'data-[state=open]:animate-in data-[state=closed]:animate-out',
              'data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom',
              className,
            )}
            style={{ paddingBottom: 'env(safe-area-inset-bottom, 0)' }}
          >
            {/* Decorative drag handle */}
            <div className="flex justify-center pt-2">
              <span className="h-1 w-10 rounded-full bg-text3/40" aria-hidden />
            </div>

            {(title || subtitle || trailing) && (
              <header className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 px-4 py-3">
                <span aria-hidden />
                <div className="text-center">
                  {title && (
                    <DialogPrimitive.Title className="font-display text-base font-semibold text-text">
                      {title}
                    </DialogPrimitive.Title>
                  )}
                  {subtitle && (
                    <p className="mt-0.5 text-xs text-text3">{subtitle}</p>
                  )}
                </div>
                <div className="justify-self-end">{trailing}</div>
              </header>
            )}
            {!title && !subtitle && !trailing && (
              <DialogPrimitive.Title className="sr-only">
                Меню действий
              </DialogPrimitive.Title>
            )}

            <div className={cn(!title && !subtitle && 'pt-2', 'px-1 pb-2')}>
              {children}
            </div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    )
  },
)

/**
 * Convenience row inside a BottomSheet — leading icon, label, optional
 * trailing element (checkmark, chevron, badge).
 */
export function BottomSheetItem({
  icon,
  children,
  trailing,
  onClick,
  destructive,
  disabled,
}: {
  icon?: ReactNode
  children: ReactNode
  trailing?: ReactNode
  onClick?: () => void
  destructive?: boolean
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left text-sm transition-colors',
        'hover:bg-surface focus-visible:bg-surface focus-visible:outline-none',
        destructive ? 'text-red' : 'text-text',
        disabled && 'pointer-events-none opacity-50',
      )}
    >
      {icon && (
        <span className="flex h-5 w-5 shrink-0 items-center justify-center text-text2">
          {icon}
        </span>
      )}
      <span className="flex-1 truncate">{children}</span>
      {trailing && <span className="shrink-0 text-text3">{trailing}</span>}
    </button>
  )
}

export const BottomSheetClose = DialogPrimitive.Close
