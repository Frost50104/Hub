import { Bell, Palette } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { cn } from '@/lib/cn'

const TABS = [
  { to: 'notifications', label: 'Уведомления', icon: Bell },
  { to: 'appearance', label: 'Оформление', icon: Palette },
] as const

export function SettingsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6 py-4 md:py-8">
      <header className="space-y-1">
        <h1 className="font-display text-2xl font-bold text-text">Настройки</h1>
        <p className="text-sm text-text2">
          Управление учётной записью и уведомлениями.
        </p>
      </header>

      <div className="grid gap-6 md:grid-cols-[200px_1fr]">
        <nav className="flex gap-1 overflow-x-auto md:flex-col md:overflow-x-visible">
          {TABS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-surface text-text'
                    : 'text-text2 hover:bg-glass hover:text-text',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <section className="glass min-w-0 p-5">
          <Outlet />
        </section>
      </div>

      <footer className="border-t border-glass-border pt-4 text-xs text-text3">
        Версия <span className="font-mono text-text2">{__APP_VERSION__}</span>
        {__APP_MODE__ !== 'production' && ` · ${__APP_MODE__}`}
      </footer>
    </div>
  )
}
