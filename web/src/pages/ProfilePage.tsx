import { Bell, ChevronRight, Globe, LogOut, Palette, Pencil } from 'lucide-react'
import { Link } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { Avatar } from '@/components/ui/Avatar'
import { useMe } from '@/hooks/useMe'
import { authClient } from '@/lib/auth'
import { cn } from '@/lib/cn'

const HUB_ROLE_LABEL: Record<'admin' | 'member' | 'viewer', string> = {
  admin: 'Администратор',
  member: 'Сотрудник',
  viewer: 'Наблюдатель',
}

/**
 * Mobile-only "Профиль" page (the desktop sidebar already has logout and
 * settings shortcuts). Layout mirrors Asana mobile: edit pencil left, title
 * centered, large avatar block, two-button row, sectioned settings rows.
 */
export function ProfilePage() {
  const me = useMe()
  return (
    <>
      <MobilePageHeader
        title="Учётная запись"
        trailing={
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md text-text3 hover:bg-glass hover:text-text"
            aria-label="Редактировать"
          >
            <Pencil className="h-5 w-5" />
          </button>
        }
      />

      <div className="space-y-5 px-4">
        {/* Identity block */}
        <section className="flex flex-col items-center gap-2 pt-2">
          <Avatar
            name={me.data?.full_name}
            email={me.data?.email}
            className="h-24 w-24 text-xl"
          />
          <h2 className="font-display text-xl font-semibold text-text">
            {me.data?.full_name || me.data?.email || 'Пользователь'}
          </h2>
          {me.data?.email && (
            <p className="text-sm text-text3">{me.data.email}</p>
          )}
        </section>

        {/* Workspace + product role */}
        <section>
          <SectionHeader>Учётная запись</SectionHeader>
          <ul className="overflow-hidden rounded-2xl border border-glass-border bg-bg-alt/60">
            <li className="flex items-center gap-3 px-4 py-3 active:bg-glass">
              <span
                className={cn(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-md',
                  'bg-amber/20 font-display text-[11px] font-black uppercase text-amber',
                )}
              >
                {(me.data?.tenant_slug?.slice(0, 2) ?? 'HU').toUpperCase()}
              </span>
              <span className="flex-1 text-sm text-text">
                {me.data?.tenant_slug?.toUpperCase() ?? 'Hub'}
              </span>
              {me.data?.hub_role && (
                <span className="rounded bg-glass px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-text3">
                  {HUB_ROLE_LABEL[me.data.hub_role]}
                </span>
              )}
            </li>
          </ul>
        </section>

        {/* Settings */}
        <section>
          <SectionHeader>Настройки</SectionHeader>
          <ul className="overflow-hidden rounded-2xl border border-glass-border bg-bg-alt/60">
            <li>
              <Link
                to="/settings/notifications"
                className="flex items-center gap-3 px-4 py-3 active:bg-glass"
              >
                <Bell className="h-5 w-5 text-text3" />
                <span className="flex-1 text-sm text-text">Уведомления</span>
                <ChevronRight className="h-4 w-4 text-text3" />
              </Link>
            </li>
            <li className="border-t border-glass-border/60">
              <Link
                to="/settings/appearance"
                className="flex items-center gap-3 px-4 py-3 active:bg-glass"
              >
                <Palette className="h-5 w-5 text-text3" />
                <span className="flex-1 text-sm text-text">Оформление</span>
                <ChevronRight className="h-4 w-4 text-text3" />
              </Link>
            </li>
            <li className="border-t border-glass-border/60">
              <button
                type="button"
                className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-glass"
              >
                <Globe className="h-5 w-5 text-text3" />
                <span className="flex-1 text-sm text-text">
                  Язык <span className="text-text3">(скоро)</span>
                </span>
              </button>
            </li>
          </ul>
        </section>

        {/* Logout */}
        <section>
          <button
            type="button"
            onClick={() => {
              void authClient.logout()
            }}
            className="flex w-full items-center justify-center gap-2 rounded-2xl border border-red/30 bg-bg-alt/60 px-4 py-3 text-sm font-medium text-red active:bg-red/10"
          >
            <LogOut className="h-4 w-4" />
            Выйти
          </button>
        </section>
      </div>
    </>
  )
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="px-2 pb-1 text-[11px] uppercase tracking-wider text-text3">
      {children}
    </h2>
  )
}
