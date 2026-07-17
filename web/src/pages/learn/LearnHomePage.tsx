import {
  Archive,
  BookOpen,
  Building2,
  ClipboardList,
  Clock,
  GraduationCap,
  Newspaper,
  ScrollText,
  ShoppingBag,
  Trophy,
  Users,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { useRecent } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'

function greeting(): string {
  const h = new Date().getHours()
  if (h < 6) return 'Доброй ночи'
  if (h < 12) return 'Доброе утро'
  if (h < 18) return 'Добрый день'
  return 'Добрый вечер'
}

const READY_SECTIONS = [
  {
    to: '/learn/library',
    icon: BookOpen,
    title: 'Библиотека',
    text: 'Инструкции, регламенты, бланки',
  },
  {
    to: '/learn/news',
    icon: Newspaper,
    title: 'Новости',
    text: 'Объявления и события компании',
  },
  {
    to: '/learn/surveys',
    icon: ClipboardList,
    title: 'Опросы',
    text: 'eNPS, пульс-опросы и обратная связь',
  },
] as const

const UPCOMING = [
  { icon: GraduationCap, title: 'Обучение', text: 'Курсы, уроки и тесты' },
  { icon: ShoppingBag, title: 'Ассортимент', text: 'Карточки товаров для работы с гостями' },
  { icon: Trophy, title: 'Рейтинг', text: 'Баллы за активность и обучение' },
] as const

const ADMIN_LINKS = [
  {
    to: '/learn/admin/org',
    icon: Building2,
    title: 'Оргструктура',
    text: 'Должности, магазины, франчайзи, отделы, группы',
  },
  {
    to: '/learn/admin/employees',
    icon: Users,
    title: 'Сотрудники',
    text: 'Карточки, архив, импорт из CSV',
  },
  {
    to: '/learn/admin/audit',
    icon: ScrollText,
    title: 'Журнал действий',
    text: 'Кто и что менял в системе',
  },
] as const

/**
 * Витрина learn-пространства. Ф0 — каркас: приветствие + карта будущих
 * разделов; с Ф1+ сюда встают блоки «назначенное обучение», «обязательные
 * ознакомления», «новинки», «опросы» (ТЗ §3).
 */
export function LearnHomePage() {
  const isDesktop = useIsDesktop()
  const me = useMe()
  const recent = useRecent()
  const isAdmin = me.data?.hub_role === 'admin'
  const firstName = me.data?.full_name?.split(/\s+/)[0] ?? ''

  const archived = me.data?.profile?.status === 'archived'
  const needsRestore = me.data?.profile_needs_restore

  return (
    <div className="mx-auto max-w-5xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Витрина" />}
      <div className="space-y-6 p-4 lg:p-8">
        {isDesktop && (
          <div>
            <h1 className="font-display text-2xl font-bold text-text">
              {greeting()}, {firstName}!
            </h1>
            <p className="mt-1 text-sm text-text2">
              Пространство обучения и знаний UPPETIT строится — разделы будут
              включаться по мере готовности.
            </p>
          </div>
        )}

        {(archived || needsRestore) && (
          <div className="flex items-start gap-3 rounded-xl border border-glass-border bg-surface p-4">
            <Archive className="mt-0.5 h-5 w-5 shrink-0 text-amber" />
            <div>
              <p className="text-sm font-semibold text-text">
                {archived ? 'Ваша карточка сотрудника в архиве' : 'Карточка ожидает восстановления'}
              </p>
              <p className="mt-0.5 text-xs text-text2">
                Материалы обучения недоступны. Обратитесь к администратору или в
                отдел персонала.
              </p>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {READY_SECTIONS.map(({ to, icon: Icon, title, text }) => (
            <Link
              key={to}
              to={to}
              className="rounded-xl border border-glass-border bg-glass p-4 transition-colors hover:border-amber/40 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            >
              <Icon className="h-5 w-5 text-amber" />
              <p className="mt-3 text-sm font-semibold text-text">{title}</p>
              <p className="mt-0.5 text-xs text-text3">{text}</p>
            </Link>
          ))}
          {UPCOMING.map(({ icon: Icon, title, text }) => (
            <div
              key={title}
              className="rounded-xl border border-glass-border bg-glass p-4 opacity-70"
            >
              <div className="flex items-center justify-between">
                <Icon className="h-5 w-5 text-text3" />
                <span className="rounded bg-surface px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-text3">
                  скоро
                </span>
              </div>
              <p className="mt-3 text-sm font-semibold text-text">{title}</p>
              <p className="mt-0.5 text-xs text-text3">{text}</p>
            </div>
          ))}
        </div>

        {(recent.data?.length ?? 0) > 0 && (
          <div>
            <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text3">
              <Clock className="h-3.5 w-3.5" /> Недавнее
            </h2>
            <ul className="divide-y divide-glass-border rounded-xl border border-glass-border bg-glass">
              {recent.data!.map((item) => (
                <li key={item.object_type + item.object_id}>
                  <Link
                    to={item.url_path}
                    className="block px-4 py-2 text-sm text-text hover:bg-surface/50"
                  >
                    {item.title}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}

        {isAdmin && (
          <div>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-text3">
              Управление
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {ADMIN_LINKS.map(({ to, icon: Icon, title, text }) => (
                <Link
                  key={to}
                  to={to}
                  className="rounded-xl border border-glass-border bg-glass p-4 transition-colors hover:border-amber/40 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                >
                  <Icon className="h-5 w-5 text-amber" />
                  <p className="mt-3 text-sm font-semibold text-text">{title}</p>
                  <p className="mt-0.5 text-xs text-text3">{text}</p>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
