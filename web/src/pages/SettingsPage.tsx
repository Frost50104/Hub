import { Bell, LogOut, Palette, RefreshCw, User } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { Avatar } from '@/components/ui/Avatar'
import { Button } from '@/components/ui/Button'
import { useAppUpdate } from '@/hooks/useAppUpdate'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useLearnProfile } from '@/hooks/useLearn'
import { useMe } from '@/hooks/useMe'
import { authClient } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { HUB_ROLE_BADGE } from '@/lib/learn'

const TABS = [
  { to: 'account', label: 'Учётная запись', icon: User },
  { to: 'notifications', label: 'Уведомления', icon: Bell },
  { to: 'appearance', label: 'Оформление', icon: Palette },
] as const

/**
 * «Профиль и настройки» — ОДИН экран: у сотрудника одна учётная запись, и
 * разделять «кто я» и «как мне приходят уведомления» на два маршрута значило
 * заставлять его искать выход из аккаунта в другом месте. Три раздела — один
 * и тот же экран в обоих пространствах: «Учётная запись» несёт данные
 * сотрудника, два других — настройки. Бывший `/profile` редиректит сюда.
 */
export function SettingsPage() {
  const isDesktop = useIsDesktop()
  const me = useMe()
  const learn = useLearnProfile()
  const name = me.data?.full_name || me.data?.email || '—'
  const roleLabel = me.data?.hub_role ? HUB_ROLE_BADGE[me.data.hub_role] : null
  const tenant = me.data?.tenant_slug?.toUpperCase()
  const logout = () => {
    void authClient.logout()
  }

  const tabs = (
    <nav
      // `shrink-0` обязателен: контейнер вкладок — прямой ребёнок колоночного
      // флекса со скроллом; без запрета сжатия он схлопывался до 13px и от
      // пилюль 44px оставались верхушки.
      className={cn(
        'flex shrink-0 gap-1.5',
        isDesktop ? 'flex-col' : 'overflow-x-auto px-4 pb-1 [scrollbar-width:none]',
      )}
    >
      {TABS.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            cn(
              'flex shrink-0 items-center gap-2 font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
              isDesktop
                ? 'min-h-10 rounded-lg px-3 text-[14px]'
                : 'min-h-11 rounded-full border px-4 text-[14px]',
              isActive
                ? isDesktop
                  ? 'bg-surface text-text'
                  : 'border-transparent bg-surface text-text'
                : isDesktop
                  ? 'text-text2 hover:bg-glass hover:text-text'
                  : 'border-glass-border text-text2 hover:text-text',
            )
          }
        >
          {isDesktop && <Icon className="h-4 w-4" />}
          {label}
        </NavLink>
      ))}
    </nav>
  )

  const version = (
    <span className="text-[14px] text-text2">
      Версия <span className="font-mono text-text">{__APP_VERSION__}</span>
      {__APP_MODE__ !== 'production' && ` · ${__APP_MODE__}`}
    </span>
  )

  if (!isDesktop) {
    return (
      <div className="flex min-h-full flex-col gap-4 pb-8">
        <header
          className="flex items-center gap-3 px-4 pb-2"
          style={{ paddingTop: 'calc(env(safe-area-inset-top, 0) + 1rem)' }}
        >
          <Avatar
            name={me.data?.full_name}
            email={me.data?.email}
            src={learn.data?.avatar_url ?? me.data?.avatar_url}
            className="h-[52px] w-[52px] text-[18px] font-display font-bold"
          />
          <div className="min-w-0">
            <h1 className="truncate font-display text-[22px] font-bold leading-[1.2] text-text">{name}</h1>
            <p className="truncate text-[13px] text-text2">
              {[me.data?.email, roleLabel].filter(Boolean).join(' · ')}
            </p>
          </div>
        </header>
        {tabs}
        <section className="flex min-w-0 flex-col gap-5 px-4">
          <Outlet />
        </section>
        <footer className="mt-2 flex flex-col gap-3 px-4">
          {version}
          <UpdateAppButton className="w-full justify-center" />
          {/* «Выйти» — последнее действие экрана и единственное красное. */}
          <Button
            variant="secondary"
            className="h-12 w-full justify-center border-red/40 text-[15px] font-semibold text-red hover:bg-red/10"
            onClick={logout}
          >
            <LogOut className="h-4 w-4" />
            Выйти
          </Button>
        </footer>
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-[940px] flex-col gap-[22px] px-6 pb-10 pt-7">
      <header className="flex flex-wrap items-center gap-4">
        <Avatar
          name={me.data?.full_name}
          email={me.data?.email}
          src={learn.data?.avatar_url ?? me.data?.avatar_url}
          className="h-16 w-16 text-[20px] font-display font-bold"
        />
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-display text-[24px] font-bold leading-[1.2] text-text">{name}</h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-2 text-[14px] text-text2">
            {me.data?.email && <span>{me.data.email}</span>}
            {tenant && <Chip>{tenant}</Chip>}
            {roleLabel && <Chip>{roleLabel}</Chip>}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={logout}>
          <LogOut className="h-4 w-4" />
          Выйти
        </Button>
      </header>

      <div className="grid gap-[22px] md:grid-cols-[200px_1fr]">
        {tabs}
        <section className="flex min-w-0 flex-col gap-5 rounded-[14px] border border-glass-border bg-tint p-5">
          <Outlet />
        </section>
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-hair pt-4">
        {version}
        <UpdateAppButton />
      </footer>
    </div>
  )
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex h-[22px] items-center rounded-md bg-surface px-2 text-[12px] font-semibold text-text2">
      {children}
    </span>
  )
}

/**
 * Ручное обновление рядом с версией: баннер «Доступно обновление» можно
 * пропустить или закрыть «Позже», и тогда вкладка неделями живёт на старом
 * бандле.
 */
function UpdateAppButton({ className }: { className?: string }) {
  const { status, checkForUpdate } = useAppUpdate()
  const busy = status !== 'idle'

  return (
    <Button variant="secondary" size="sm" onClick={checkForUpdate} disabled={busy} className={className}>
      <RefreshCw className={cn('h-4 w-4', busy && 'animate-spin')} />
      {status === 'applying' ? 'Применяем…' : 'Обновить приложение'}
    </Button>
  )
}
