import { MoreHorizontal } from 'lucide-react'
import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

interface MobilePageHeaderProps {
  /** Slot above the eyebrow/title — e.g. the SpaceSwitcher on home pages. */
  topSlot?: ReactNode
  /** Pre-title sub-line — typically the date or a small label. */
  eyebrow?: string
  /**
   * Не применять `capitalize` к eyebrow. Нужно там, где в строке есть имя
   * собственное в нижнем регистре: «Отчёты iiko» иначе превращается в
   * «Отчёты Iiko» — CSS-capitalize поднимает первую букву КАЖДОГО слова.
   */
  preserveEyebrowCase?: boolean
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
  topSlot,
  eyebrow,
  preserveEyebrowCase,
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
      {topSlot && <div className="mb-3">{topSlot}</div>}
      {eyebrow && (
        <p
          className={cn(
            'mb-1 text-xs text-text2',
            !preserveEyebrowCase && 'capitalize',
          )}
        >
          {eyebrow}
        </p>
      )}
      <div className="flex items-end justify-between gap-2">
        {/* 24px, не 30: шкала мобильных шапок из макета (Главная 23, представления
            проекта 22 — задаётся className у вызывающего). */}
        <h1 className="font-display text-[24px] font-bold leading-[1.2] text-text">
          {title}
        </h1>
        {trailing ??
          (withOverflowMenu && (
            <button
              type="button"
              onClick={onOverflowClick}
              className="-m-1.5 inline-flex h-11 w-11 items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              aria-label="Меню"
            >
              <MoreHorizontal className="h-5 w-5" />
            </button>
          ))}
      </div>
    </header>
  )
}
