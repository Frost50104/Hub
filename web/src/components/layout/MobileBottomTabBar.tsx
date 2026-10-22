import { type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

import { LearnMenuSheet } from './LearnMenuSheet'
import { ADMIN_NAV, LEARN_MENU_ITEMS } from './learnNav'
import { LEARN_TABS, TASK_TABS } from './mobileTabs'
import { useUnreadCount } from '@/hooks/useNotifications'
import { cn } from '@/lib/cn'
import { type Space } from '@/lib/workspace'

// Подсветка «Меню» выводится из тех же массивов learnNav.ts, что и содержимое
// sheet'а — списки не разъедутся. Детальные роуты без своей вкладки
// (/learn/certificates/:id, /learn/lessons/:id) не подсвечивают ничего — как
// и до этой доработки.
const MENU_DESTINATIONS = [
  ...LEARN_MENU_ITEMS.map((i) => i.to),
  '/settings',
  ...ADMIN_NAV.map((i) => i.to),
]

function tabInner(Icon: LucideIcon, label: string, dot: boolean) {
  return (
    <>
      <span className="relative">
        <Icon className="h-6 w-6" strokeWidth={1.6} />
        {dot && (
          <span className="absolute -right-0.5 -top-0.5 inline-block h-1.5 w-1.5 rounded-full bg-red" />
        )}
      </span>
      <span className="leading-none">{label}</span>
    </>
  )
}

/**
 * Bottom tab bar (5 entries) — flat Desk-style (see Layout.jsx в AXO_bot_web):
 * компактные 50px, без подложки под активной иконкой, актив — только цвет
 * (amber) + вес подписи. In the learn space the fifth tab is a button
 * opening `LearnMenuSheet`.
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
      // 56px и подпись 11px — геометрия из спеки редизайна: пункт таб-бара
      // должен проходить порог тап-таргета целиком, а не только иконкой.
      'flex min-h-14 w-full flex-col items-center justify-center gap-[3px] pt-2 text-[11px] transition-colors',
      active ? 'font-semibold text-amber' : 'font-normal text-text2 hover:text-text',
    )

  return (
    <>
      <nav
        aria-label="Главное меню"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-glass-border bg-bg-alt"
        style={{ paddingBottom: 'env(safe-area-inset-bottom, 0)' }}
      >
        <ul className="flex">
          {tabs.map((tab) => (
            <li key={tab.label} className="flex-1">
              {tab.kind === 'link' ? (
                <NavLink
                  to={tab.to}
                  end={tab.end}
                  className={({ isActive }) => itemClass(isActive)}
                >
                  {tabInner(
                    tab.icon,
                    tab.label,
                    Boolean(tab.showUnreadDot) && unreadCount > 0,
                  )}
                </NavLink>
              ) : (
                <button
                  type="button"
                  onClick={() => setMenuOpen(true)}
                  className={itemClass(menuActive)}
                  aria-haspopup="dialog"
                  aria-expanded={menuOpen}
                >
                  {tabInner(tab.icon, tab.label, false)}
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
