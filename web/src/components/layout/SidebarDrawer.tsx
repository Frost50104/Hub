import * as DialogPrimitive from '@radix-ui/react-dialog'

import { Sidebar } from './Sidebar'

interface SidebarDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Mobile off-canvas sidebar. Wraps the same `<Sidebar />` body in a Radix
 * Dialog that slides in from the left. `onItemClick` closes the drawer
 * after navigation so users don't have to dismiss it manually.
 */
export function SidebarDrawer({ open, onOpenChange }: SidebarDrawerProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className="fixed inset-y-0 left-0 z-50 w-[280px] focus:outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left"
          aria-describedby={undefined}
        >
          <DialogPrimitive.Title className="sr-only">
            Навигация
          </DialogPrimitive.Title>
          <Sidebar onItemClick={() => onOpenChange(false)} />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
