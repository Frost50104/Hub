import { CheckSquare, GraduationCap } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'

import { cn } from '@/lib/cn'
import { spaceFromPath, useWorkspace, type Space } from '@/lib/workspace'

const SPACES: { key: Space; label: string; icon: typeof CheckSquare; to: string }[] = [
  { key: 'tasks', label: 'Задачи', icon: CheckSquare, to: '/' },
  { key: 'learn', label: 'Обучение', icon: GraduationCap, to: '/learn' },
]

/**
 * Переключатель пространств «Задачи | Обучение» (segmented control).
 * Активное пространство выводится из URL; клик — навигация в корень
 * пространства + запоминание выбора для будущих сессий.
 */
export function SpaceSwitcher({ className }: { className?: string }) {
  const location = useLocation()
  const navigate = useNavigate()
  const rememberSpace = useWorkspace((s) => s.rememberSpace)
  const active = spaceFromPath(location.pathname)

  return (
    <div
      role="tablist"
      aria-label="Пространство"
      className={cn(
        'flex rounded-lg border border-glass-border bg-bg-alt/60 p-0.5',
        className,
      )}
    >
      {SPACES.map(({ key, label, icon: Icon, to }) => (
        <button
          key={key}
          role="tab"
          aria-selected={active === key}
          onClick={() => {
            if (active !== key) {
              rememberSpace(key)
              navigate(to)
            }
          }}
          className={cn(
            'flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-semibold transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
            active === key
              ? 'bg-surface text-amber shadow-sm'
              : 'text-text3 hover:text-text2',
          )}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </button>
      ))}
    </div>
  )
}
