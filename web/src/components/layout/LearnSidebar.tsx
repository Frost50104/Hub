import { LogOut, Settings } from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'

import { ADMIN_NAV, adminSegmentsFor, coursesSectionTitle, LEARN_NAV, type LearnNavItem } from './learnNav'
import { SpaceSwitcher } from './SpaceSwitcher'
import { Avatar } from '@/components/ui/Avatar'
import { useMe } from '@/hooks/useMe'
import { useUnreadCount } from '@/hooks/useNotifications'
import { authClient } from '@/lib/auth'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/cn'
import { HubRoleChip } from '@/components/layout/HubRoleChip'

function NavEntry({
  item,
  unreadCount,
  onItemClick,
}: {
  item: LearnNavItem
  unreadCount: number
  onItemClick?: () => void
}) {
  const { to, label, icon: Icon, end, badge, soon } = item
  if (soon) {
    return (
      <span
        className="flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-text3/60"
        title="Скоро"
      >
        <Icon className="h-4 w-4" />
        <span className="flex-1">{label}</span>
        <span className="rounded bg-glass px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-text3">
          скоро
        </span>
      </span>
    )
  }
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onItemClick}
      className={({ isActive }) =>
        cn(
          'flex h-[34px] items-center gap-[9px] rounded-[9px] px-2 text-[14px] transition-colors',
          isActive
            ? 'bg-surface font-semibold text-text'
            : 'font-medium text-text2 hover:bg-glass hover:text-text',
        )
      }
    >
      <Icon className="h-4 w-4" />
      <span className="flex-1">{label}</span>
      {badge && unreadCount > 0 && (
        <span className="rounded-full bg-amber px-1.5 py-0.5 text-[12px] font-semibold leading-none text-on-amber">
          {unreadCount > 99 ? '99+' : unreadCount}
        </span>
      )}
    </NavLink>
  )
}

export function LearnSidebar({ onItemClick }: { onItemClick?: () => void } = {}) {
  const theme = useTheme((s) => s.theme)
  const me = useMe()
  const unread = useUnreadCount()
  const unreadCount = unread.data?.count ?? 0
  const isAdmin = adminSegmentsFor(me.data).length > 0
  const coursesTitle = coursesSectionTitle(
    me.data?.profile?.content_role,
    me.data?.hub_role,
  )

  return (
    <aside className="glass flex h-screen w-[280px] shrink-0 flex-col gap-4 p-4 md:h-[calc(100vh-1.5rem)] md:w-[260px]">
      {/* Бренд как в Sidebar: марка-маяк + «Hub», роль — чипом у профиля. */}
      <Link to="/learn" onClick={onItemClick} className="flex items-center gap-2.5 px-1">
        <img
          src={
            theme === 'light'
              ? '/brand/signaris-mark-on-light.svg'
              : '/brand/signaris-mark-on-dark.svg'
          }
          alt="Signaris"
          className="h-[26px] w-[26px] shrink-0"
        />
        <span className="font-display text-[17px] font-black leading-none tracking-[-0.025em] text-text">
          Hub
        </span>
      </Link>

      <SpaceSwitcher />

      {/* Навигация — единственная растягивающаяся область панели. `min-h-0`
       * обязателен: без него flex-элемент не ужимается ниже своего контента и
       * у админа (11 разделов + 6 управления) футер с профилем выезжает за
       * пределы `h-[calc(100vh-1.5rem)]`. */}
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
        <nav className="flex flex-col gap-0.5">
          {LEARN_NAV.map((item) => (
            <NavEntry
              key={item.to + item.label}
              // Раздел курсов называется по роли — и в меню, и в заголовке.
              item={item.to === '/learn/courses' ? { ...item, label: coursesTitle } : item}
              unreadCount={unreadCount}
              onItemClick={onItemClick}
            />
          ))}
        </nav>

        {isAdmin && (
          <div className="flex flex-col gap-0.5">
            <p className="px-2 pb-0.5 pt-2 text-[12px] font-semibold uppercase tracking-wider text-text2">
              Управление
            </p>
            {ADMIN_NAV.map((item) => (
              <NavEntry
                key={item.to}
                item={item}
                unreadCount={unreadCount}
                onItemClick={onItemClick}
              />
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-glass-border pt-3">
        <div className="flex items-center gap-2 overflow-hidden">
          <Avatar
            name={me.data?.full_name}
            email={me.data?.email}
            src={me.data?.avatar_url}
            className="h-7 w-7 text-[13px]"
          />
          <div className="min-w-0">
            <p className="flex min-w-0 items-center gap-1.5">
              <span className="min-w-0 truncate text-[13px] font-medium leading-[1.35] text-text">
                {me.data?.full_name || me.data?.email || '—'}
              </span>
              {me.data?.hub_role && <HubRoleChip role={me.data.hub_role} />}
            </p>
            <p className="truncate text-[12px] leading-[1.35] text-text2">{me.data?.email ?? ''}</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Link
            to="/settings/notifications"
            onClick={onItemClick}
            className="rounded p-1.5 text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            aria-label="Настройки"
            title="Настройки"
          >
            <Settings className="h-4 w-4" />
          </Link>
          <button
            onClick={() => {
              void authClient.logout()
            }}
            className="rounded p-1.5 text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            aria-label="Выйти"
            title="Выйти"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  )
}
