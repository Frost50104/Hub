import * as SwitchPrimitive from '@radix-ui/react-switch'
import { forwardRef } from 'react'

import { cn } from '@/lib/cn'

export const Switch = forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={cn(
      // Дорожка 44×24 (спека редизайна) — она же визуал; порог тап-таргета
      // добирает обёртка 44×44 у вызывающего, трогать геометрию дорожки нельзя.
      'peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full p-0.5',
      'border border-glass-border transition-colors',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
      'disabled:cursor-not-allowed disabled:opacity-50',
      'data-[state=checked]:bg-amber data-[state=unchecked]:bg-surface',
      className,
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb
      className={cn(
        // Накладка включённого — --on-amber (#08080E, не флипается): --bg в
        // светлой теме почти той же светлоты, что амбер, и давал 1,73:1 на
        // единственном индикаторе состояния тумблера.
        'pointer-events-none block h-5 w-5 rounded-full shadow ring-0 transition-transform',
        'data-[state=checked]:translate-x-5 data-[state=checked]:bg-on-amber',
        'data-[state=unchecked]:translate-x-0 data-[state=unchecked]:bg-text2',
      )}
    />
  </SwitchPrimitive.Root>
))
Switch.displayName = 'Switch'
