import {
  BarChart3,
  BookOpen,
  Bot,
  ClipboardList,
  Building2,
  GraduationCap,
  Handshake,
  Inbox,
  LogOut,
  Newspaper,
  ScrollText,
  Settings,
  ShoppingBag,
  Sparkles,
  Trophy,
  Users,
  Workflow,
} from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'

import { SpaceSwitcher } from './SpaceSwitcher'
import { Avatar } from '@/components/ui/Avatar'
import { useMe } from '@/hooks/useMe'
import { useUnreadCount } from '@/hooks/useNotifications'
import { authClient } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { HUB_ROLE_BADGE } from '@/lib/learn'

interface LearnNavItem {
  to: string
  label: string
  icon: typeof GraduationCap
  end?: boolean
  badge?: boolean
  soon?: boolean
}

// Разделы включаются по мере этапов Ф1–Ф4; до готовности — «скоро» (disabled).
const LEARN_NAV: LearnNavItem[] = [
  { to: '/learn', label: 'Витрина', icon: Sparkles, end: true },
  { to: '/learn/courses', label: 'Моё обучение', icon: GraduationCap },
  { to: '/learn/library', label: 'Библиотека', icon: BookOpen },
  { to: '/learn/news', label: 'Новости', icon: Newspaper },
  { to: '/learn/surveys', label: 'Опросы', icon: ClipboardList },
  { to: '/learn/products', label: 'Ассортимент', icon: ShoppingBag },
  { to: '/learn/rating', label: 'Рейтинг', icon: Trophy },
  { to: '/learn/assistant', label: 'AI-помощник', icon: Bot },
  { to: '/learn/shifts', label: 'Биржа смен', icon: Handshake },
  { to: '/inbox', label: 'Входящие', icon: Inbox, badge: true },
]

const ADMIN_NAV: LearnNavItem[] = [
  { to: '/learn/admin/org', label: 'Оргструктура', icon: Building2 },
  { to: '/learn/admin/employees', label: 'Сотрудники', icon: Users },
  { to: '/learn/admin/review', label: 'Проверка тестов', icon: ClipboardList },
  { to: '/learn/admin/analytics', label: 'Аналитика', icon: BarChart3 },
  { to: '/learn/admin/automations', label: 'Автосценарии', icon: Workflow },
  { to: '/learn/admin/audit', label: 'Журнал', icon: ScrollText },
]

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
          'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium transition-colors',
          isActive ? 'bg-surface text-text' : 'text-text2 hover:bg-glass hover:text-text',
        )
      }
    >
      <Icon className="h-4 w-4" />
      <span className="flex-1">{label}</span>
      {badge && unreadCount > 0 && (
        <span className="rounded-full bg-amber px-1.5 py-0.5 text-[10px] font-semibold text-on-amber">
          {unreadCount > 99 ? '99+' : unreadCount}
        </span>
      )}
    </NavLink>
  )
}

export function LearnSidebar({ onItemClick }: { onItemClick?: () => void } = {}) {
  const me = useMe()
  const unread = useUnreadCount()
  const unreadCount = unread.data?.count ?? 0
  const isAdmin = me.data?.hub_role === 'admin'

  return (
    <aside className="glass flex h-screen w-[280px] shrink-0 flex-col gap-4 p-4 md:h-[calc(100vh-1.5rem)] md:w-[260px]">
      <Link to="/learn" onClick={onItemClick} className="flex items-center gap-2 px-1">
        <img src="/brand/signaris-horizontal-on-dark.svg" alt="Signaris" className="h-6" />
        <span className="font-display text-lg font-black leading-none tracking-tight">
          Hub
        </span>
        {me.data?.hub_role && (
          <span className="ml-1 text-[10px] font-semibold uppercase tracking-widest text-text3">
            {HUB_ROLE_BADGE[me.data.hub_role]}
          </span>
        )}
      </Link>

      <SpaceSwitcher />

      <nav className="flex flex-col gap-0.5">
        {LEARN_NAV.map((item) => (
          <NavEntry
            key={item.to + item.label}
            item={item}
            unreadCount={unreadCount}
            onItemClick={onItemClick}
          />
        ))}
      </nav>

      {isAdmin && (
        <div className="flex flex-col gap-0.5">
          <p className="px-2 pb-0.5 pt-2 text-[11px] font-semibold uppercase tracking-wider text-text3">
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

      <div className="flex-1" />

      <div className="flex items-center justify-between gap-2 border-t border-glass-border pt-3">
        <div className="flex items-center gap-2 overflow-hidden">
          <Avatar
            name={me.data?.full_name}
            email={me.data?.email}
            className="h-7 w-7 text-[10px]"
          />
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-text">
              {me.data?.full_name || me.data?.email || '—'}
            </p>
            <p className="truncate text-[10px] text-text3">{me.data?.email ?? ''}</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Link
            to="/settings/notifications"
            onClick={onItemClick}
            className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            aria-label="Настройки"
            title="Настройки"
          >
            <Settings className="h-4 w-4" />
          </Link>
          <button
            onClick={() => {
              void authClient.logout()
            }}
            className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
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
