import { MoreHorizontal } from 'lucide-react'
import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

interface MobilePageHeaderProps {
  /** Pre-title sub-line — typically the date or a small label. */
  eyebrow?: string
  /** Big page title (rendered as `<h1>`). */
  title: string
  /** Optional trailing action — a button group, icon button, etc. */
  trailing?: ReactNode
  /** When true, shows the standard "more" overflow button on the right. */
  withOverflowMenu?: boolean
  onOverflowClick?: () => void
  className?: string
}

/**
 * Asana-style mobile page header — pre-line (eyebrow) + giant title +
 * optional trailing action. No back button: bottom tab bar IS the nav.
 * Sticks below the iOS status bar via `pt-safe`.
 */
export function MobilePageHeader({
  eyebrow,
  title,
  trailing,
  withOverflowMenu,
  onOverflowClick,
  className,
}: MobilePageHeaderProps) {
  return (
    <header
      className={cn('px-4 pb-3 pt-3', className)}
      style={{ paddingTop: 'calc(env(safe-area-inset-top, 0) + 0.75rem)' }}
    >
      {eyebrow && (
        <p className="mb-1 text-xs text-text2 capitalize">{eyebrow}</p>
      )}
      <div className="flex items-end justify-between gap-2">
        <h1 className="font-display text-3xl font-bold leading-tight text-text">
          {title}
        </h1>
        {trailing ??
          (withOverflowMenu && (
            <button
              type="button"
              onClick={onOverflowClick}
              className="inline-flex h-9 w-9 items-center justify-center rounded-md text-text3 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              aria-label="Меню"
            >
              <MoreHorizontal className="h-5 w-5" />
            </button>
          ))}
      </div>
    </header>
  )
}
