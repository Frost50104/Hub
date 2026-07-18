import { Bell, CheckCircle2, GraduationCap, Home, Search, Sparkles, User } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { useUnreadCount } from '@/hooks/useNotifications'
import { cn } from '@/lib/cn'
import { type Space } from '@/lib/workspace'

interface TabDef {
  to: string
  label: string
  icon: typeof Home
  end?: boolean
  showUnreadDot?: boolean
}

const TASK_TABS: TabDef[] = [
  { to: '/', label: 'Главная', icon: Home, end: true },
  { to: '/my', label: 'Мои задачи', icon: CheckCircle2 },
  { to: '/inbox', label: 'Входящие', icon: Bell, showUnreadDot: true },
  { to: '/search', label: 'Поиск', icon: Search },
  { to: '/profile', label: 'Профиль', icon: User },
]

const LEARN_TABS: TabDef[] = [
  { to: '/learn', label: 'Витрина', icon: Sparkles, end: true },
  { to: '/learn/courses', label: 'Обучение', icon: GraduationCap },
  { to: '/inbox', label: 'Входящие', icon: Bell, showUnreadDot: true },
  { to: '/search', label: 'Поиск', icon: Search },
  { to: '/profile', label: 'Профиль', icon: User },
]

/**
 * Asana-style bottom tab bar (5 entries). Active tab fills a circle around
 * the icon (theme-aware). Inactive tabs render the outline icon + label.
 *
 * Sits fixed at the bottom of the viewport. Adds `safe-area-inset-bottom`
 * padding so it stays clear of the iOS home indicator without doubling the
 * height in browsers without a notch.
 */
export function MobileBottomTabBar({ space = 'tasks' }: { space?: Space }) {
  const unread = useUnreadCount()
  const unreadCount = unread.data?.count ?? 0
  const tabs = space === 'learn' ? LEARN_TABS : TASK_TABS

  return (
    <nav
      aria-label="Главное меню"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-glass-border bg-bg-alt/95 backdrop-blur"
      style={{ paddingBottom: 'env(safe-area-inset-bottom, 0)' }}
    >
      <ul className="flex items-end justify-around px-1 pb-1 pt-2">
        {tabs.map(({ to, label, icon: Icon, end, showUnreadDot }) => (
          <li key={to + label} className="flex-1">
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'group flex flex-col items-center gap-1 rounded-md py-1 text-[10px] font-medium transition-colors',
                  isActive ? 'text-amber' : 'text-text3 hover:text-text2',
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className={cn(
                      'relative flex h-9 w-9 items-center justify-center rounded-full transition-colors',
                      isActive ? 'bg-surface text-amber' : 'bg-transparent',
                    )}
                  >
                    <Icon className="h-5 w-5" strokeWidth={isActive ? 2.2 : 1.8} />
                    {showUnreadDot && unreadCount > 0 && (
                      <span className="absolute right-1 top-1 inline-block h-1.5 w-1.5 rounded-full bg-red" />
                    )}
                  </span>
                  <span className="leading-none">{label}</span>
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
