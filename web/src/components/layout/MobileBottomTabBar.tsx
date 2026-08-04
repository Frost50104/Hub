import {
  Bell,
  CheckCircle2,
  GraduationCap,
  Home,
  Menu,
  Search,
  Sparkles,
  User,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

import { LearnMenuSheet } from './LearnMenuSheet'
import { ADMIN_NAV, LEARN_MENU_ITEMS } from './learnNav'
import { useUnreadCount } from '@/hooks/useNotifications'
import { cn } from '@/lib/cn'
import { type Space } from '@/lib/workspace'

type TabDef =
  | {
      kind: 'link'
      to: string
      label: string
      icon: typeof Home
      end?: boolean
      showUnreadDot?: boolean
    }
  | { kind: 'menu'; label: string; icon: typeof Home }

const TASK_TABS: TabDef[] = [
  { kind: 'link', to: '/', label: 'Главная', icon: Home, end: true },
  { kind: 'link', to: '/my', label: 'Мои задачи', icon: CheckCircle2 },
  { kind: 'link', to: '/inbox', label: 'Входящие', icon: Bell, showUnreadDot: true },
  { kind: 'link', to: '/search', label: 'Поиск', icon: Search },
  { kind: 'link', to: '/profile', label: 'Профиль', icon: User },
]

// В learn-наборе вкладку «Профиль» заменяет «Меню» (sheet со всеми разделами);
// Профиль доступен строкой внутри sheet'а.
const LEARN_TABS: TabDef[] = [
  { kind: 'link', to: '/learn', label: 'Витрина', icon: Sparkles, end: true },
  { kind: 'link', to: '/learn/courses', label: 'Обучение', icon: GraduationCap },
  { kind: 'link', to: '/inbox', label: 'Входящие', icon: Bell, showUnreadDot: true },
  { kind: 'link', to: '/search', label: 'Поиск', icon: Search },
  { kind: 'menu', label: 'Меню', icon: Menu },
]

// Подсветка «Меню» выводится из тех же массивов learnNav.ts, что и содержимое
// sheet'а — списки не разъедутся. Детальные роуты без своей вкладки
// (/learn/certificates/:id, /learn/lessons/:id) не подсвечивают ничего — как
// и до этой доработки.
const MENU_DESTINATIONS = [
  ...LEARN_MENU_ITEMS.map((i) => i.to),
  '/profile',
  ...ADMIN_NAV.map((i) => i.to),
]

function tabInner(Icon: typeof Home, label: string, active: boolean, dot: boolean) {
  return (
    <>
      <span
        className={cn(
          'relative flex h-9 w-9 items-center justify-center rounded-full transition-colors',
          active ? 'bg-surface text-amber' : 'bg-transparent',
        )}
      >
        <Icon className="h-5 w-5" strokeWidth={active ? 2.2 : 1.8} />
        {dot && (
          <span className="absolute right-1 top-1 inline-block h-1.5 w-1.5 rounded-full bg-red" />
        )}
      </span>
      <span className="leading-none">{label}</span>
    </>
  )
}

/**
 * Asana-style bottom tab bar (5 entries). Active tab fills a circle around
 * the icon (theme-aware). Inactive tabs render the outline icon + label.
 * In the learn space the fifth tab is a button opening `LearnMenuSheet`.
 *
 * Sits fixed at the bottom of the viewport. Adds `safe-area-inset-bottom`
 * padding so it stays clear of the iOS home indicator without doubling the
 * height in browsers without a notch.
 */
export function MobileBottomTabBar({ space = 'tasks' }: { space?: Space }) {
  const unread = useUnreadCount()
  const unreadCount = unread.data?.count ?? 0
  const { pathname } = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const tabs = space === 'learn' ? LEARN_TABS : TASK_TABS

  const menuActive = MENU_DESTINATIONS.some(
    (to) => pathname === to || pathname.startsWith(to + '/'),
  )

  const itemClass = (active: boolean) =>
    cn(
      'group flex flex-col items-center gap-1 rounded-md py-1 text-[10px] font-medium transition-colors',
      active ? 'text-amber' : 'text-text3 hover:text-text2',
    )

  return (
    <>
      <nav
        aria-label="Главное меню"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-glass-border bg-bg-alt/95 backdrop-blur"
        style={{ paddingBottom: 'env(safe-area-inset-bottom, 0)' }}
      >
        <ul className="flex items-end justify-around px-1 pb-1 pt-2">
          {tabs.map((tab) => (
            <li key={tab.label} className="flex-1">
              {tab.kind === 'link' ? (
                <NavLink
                  to={tab.to}
                  end={tab.end}
                  className={({ isActive }) => itemClass(isActive)}
                >
                  {({ isActive }) =>
                    tabInner(
                      tab.icon,
                      tab.label,
                      isActive,
                      Boolean(tab.showUnreadDot) && unreadCount > 0,
                    )
                  }
                </NavLink>
              ) : (
                <button
                  type="button"
                  onClick={() => setMenuOpen(true)}
                  className={cn('w-full', itemClass(menuActive))}
                  aria-haspopup="dialog"
                  aria-expanded={menuOpen}
                >
                  {tabInner(tab.icon, tab.label, menuActive, false)}
                </button>
              )}
            </li>
          ))}
        </ul>
      </nav>
      {space === 'learn' && (
        <LearnMenuSheet open={menuOpen} onOpenChange={setMenuOpen} />
      )}
    </>
  )
}
