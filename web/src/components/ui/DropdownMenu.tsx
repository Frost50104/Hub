import * as DropdownPrimitive from '@radix-ui/react-dropdown-menu'
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from 'react'

import { cn } from '@/lib/cn'

export const DropdownMenu = DropdownPrimitive.Root
export const DropdownMenuTrigger = DropdownPrimitive.Trigger
export const DropdownMenuPortal = DropdownPrimitive.Portal
export const DropdownMenuGroup = DropdownPrimitive.Group

export const DropdownMenuContent = forwardRef<
  ElementRef<typeof DropdownPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DropdownPrimitive.Content>
>(({ className, sideOffset = 4, collisionPadding = 8, ...props }, ref) => (
  <DropdownMenuPortal>
    <DropdownPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      collisionPadding={collisionPadding}
      className={cn(
        'glass-solid z-50 min-w-[8rem] overflow-hidden rounded-lg p-1 text-text shadow-glass',
        // Потолок высоты + прокрутка — ОБЯЗАТЕЛЬНЫ, и не ради красоты (ОС
        // 14.09 «список имён не двигается пальцем»). Radix Menu в модальном
        // режиме оборачивает САМ Content в `RemoveScroll`, а тот считает
        // элемент с `overflow: hidden` непрокручиваемым, не находит внутри ни
        // одного скроллера и ОТМЕНЯЕТ каждый `touchmove`. Без этой пары
        // выпадашка исполнителей на iPhone была 889px при экране 800, стояла
        // на `top: −463` и не двигалась вовсе.
        //
        // Потолок берём у Radix, а не константой: меню умеет строиться и
        // вверх, и `max-h-[60vh]` оставил бы часть списка за экраном.
        // `overflow-hidden` остаётся ради скруглений по X — `twMerge` классы
        // не схлопывает, в итоге `overflow-x: hidden, overflow-y: auto`.
        'max-h-[var(--radix-dropdown-menu-content-available-height)] overflow-y-auto overscroll-contain',
        'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
        className,
      )}
      {...props}
    />
  </DropdownMenuPortal>
))
DropdownMenuContent.displayName = DropdownPrimitive.Content.displayName

export const DropdownMenuItem = forwardRef<
  ElementRef<typeof DropdownPrimitive.Item>,
  ComponentPropsWithoutRef<typeof DropdownPrimitive.Item> & { destructive?: boolean }
>(({ className, destructive, ...props }, ref) => (
  <DropdownPrimitive.Item
    ref={ref}
    className={cn(
      'relative flex cursor-pointer select-none items-center rounded-md px-2 py-1.5 text-sm outline-none',
      'transition-colors focus:bg-surface data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
      destructive ? 'text-red focus:text-red' : 'text-text',
      className,
    )}
    {...props}
  />
))
DropdownMenuItem.displayName = DropdownPrimitive.Item.displayName

export const DropdownMenuSeparator = forwardRef<
  ElementRef<typeof DropdownPrimitive.Separator>,
  ComponentPropsWithoutRef<typeof DropdownPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <DropdownPrimitive.Separator
    ref={ref}
    className={cn('my-1 h-px bg-glass-border', className)}
    {...props}
  />
))
DropdownMenuSeparator.displayName = DropdownPrimitive.Separator.displayName

export const DropdownMenuLabel = forwardRef<
  ElementRef<typeof DropdownPrimitive.Label>,
  ComponentPropsWithoutRef<typeof DropdownPrimitive.Label>
>(({ className, ...props }, ref) => (
  <DropdownPrimitive.Label
    ref={ref}
    className={cn('px-2 py-1.5 text-sm font-semibold text-text', className)}
    {...props}
  />
))
DropdownMenuLabel.displayName = DropdownPrimitive.Label.displayName
