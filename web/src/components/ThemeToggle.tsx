import { Moon, Sun } from 'lucide-react'

import { cn } from '@/lib/cn'
import { type Theme, useTheme } from '@/lib/theme'

const OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Светлая', icon: Sun },
  { value: 'dark', label: 'Тёмная', icon: Moon },
]

/**
 * Segmented System / Light / Dark switch. Full-width by default (fills its
 * container) so it works in both the desktop sidebar footer and the mobile
 * profile page. Active segment uses the amber accent with fixed-dark ink.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const theme = useTheme((s) => s.theme)
  const setTheme = useTheme((s) => s.setTheme)

  return (
    <div
      role="radiogroup"
      aria-label="Тема оформления"
      className={cn(
        'flex gap-0.5 rounded-lg border border-glass-border bg-surface p-0.5',
        className,
      )}
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const active = theme === value
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => setTheme(value)}
            title={label}
            className={cn(
              'flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
              active
                ? 'bg-amber text-on-amber'
                : 'text-text2 hover:text-text',
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        )
      })}
    </div>
  )
}
