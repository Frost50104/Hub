import {
  Archive,
  BookOpen,
  Building2,
  CalendarClock,
  ClipboardList,
  Clock,
  GraduationCap,
  ScrollText,
  Sparkles,
  Trophy,
  Users,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useLearnHome, useRecent } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import { cn } from '@/lib/cn'
import { COURSE_TYPE_LABEL } from '@/lib/learn'

function greeting(): string {
  const h = new Date().getHours()
  if (h < 6) return 'Доброй ночи'
  if (h < 12) return 'Доброе утро'
  if (h < 18) return 'Добрый день'
  return 'Добрый вечер'
}

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

function SectionTitle({
  icon: Icon,
  children,
}: {
  icon: typeof Clock
  children: React.ReactNode
}) {
  return (
    <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text3">
      <Icon className="h-3.5 w-3.5" /> {children}
    </h2>
  )
}

/**
 * Витрина «Обучение» (Ф4, ТЗ §3): персональная сводка — обучение в работе,
 * обязательные ознакомления, новинки, активные опросы, рейтинг-виджет.
 */
export function LearnHomePage() {
  const isDesktop = useIsDesktop()
  const me = useMe()
  const home = useLearnHome()
  const recent = useRecent()
  const isAdmin = me.data?.hub_role === 'admin'
  const firstName = me.data?.full_name?.split(/\s+/)[0] ?? ''

  const archived = me.data?.profile?.status === 'archived'
  const needsRestore = me.data?.profile_needs_restore
  const data = home.data

  return (
    <div className="mx-auto max-w-5xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Витрина" />}
      <div className="space-y-6 p-4 lg:p-8">
        <div className="flex flex-wrap items-start justify-between gap-3">
          {isDesktop && (
            <h1 className="font-display text-2xl font-bold text-text">
              {greeting()}, {firstName}!
            </h1>
          )}
          {data?.rating && (
            <Link
              to="/learn/rating"
              className="flex items-center gap-2.5 rounded-xl border border-glass-border bg-glass px-3.5 py-2 transition-colors hover:border-amber/50"
            >
              <Trophy className="h-5 w-5 text-amber" />
              <span className="text-sm text-text">
                <b>{Number.isInteger(data.rating.points) ? data.rating.points : data.rating.points.toFixed(1)}</b>{' '}
                баллов
                {data.rating.rank !== null && (
                  <span className="text-text3">
                    {' '}
                    · {data.rating.rank} место из {data.rating.total_participants}
                  </span>
                )}
              </span>
            </Link>
          )}
        </div>

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

        {home.isLoading && <SkeletonRows rows={5} />}

        {data && data.courses.length > 0 && (
          <div>
            <SectionTitle icon={GraduationCap}>Моё обучение</SectionTitle>
            <div className="space-y-2">
              {data.courses.map((c) => {
                const pct =
                  c.lessons_total > 0
                    ? Math.round((c.lessons_completed / c.lessons_total) * 100)
                    : 0
                return (
                  <Link
                    key={c.id}
                    to={`/learn/courses/${c.id}`}
                    className="block rounded-xl border border-glass-border bg-glass p-3.5 transition-colors hover:border-amber/50"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="min-w-0 flex-1 truncate text-sm font-medium text-text">
                        {c.title}
                      </p>
                      <span
                        className={cn(
                          'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium',
                          c.course_type === 'mandatory'
                            ? 'bg-amber/15 text-amber'
                            : 'bg-surface text-text3',
                        )}
                      >
                        {COURSE_TYPE_LABEL[c.course_type]}
                      </span>
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface">
                        <span
                          className="block h-full rounded-full bg-amber"
                          style={{ width: `${pct}%` }}
                        />
                      </span>
                      <span className="shrink-0 text-xs text-text3">
                        {c.lessons_completed}/{c.lessons_total}
                      </span>
                      {c.due_at && (
                        <span className="inline-flex shrink-0 items-center gap-1 text-xs text-text3">
                          <CalendarClock className="h-3.5 w-3.5" />
                          до{' '}
                          {new Date(c.due_at).toLocaleDateString('ru-RU', {
                            day: 'numeric',
                            month: 'short',
                          })}
                        </span>
                      )}
                    </div>
                  </Link>
                )
              })}
            </div>
          </div>
        )}

        {data && data.pending_acks.length > 0 && (
          <div>
            <SectionTitle icon={BookOpen}>Требуют ознакомления</SectionTitle>
            <ul className="divide-y divide-glass-border rounded-xl border border-amber/40 bg-amber/5">
              {data.pending_acks.map((a) => (
                <li key={a.id}>
                  <Link
                    to={`/learn/library?m=${a.id}`}
                    className="flex items-center justify-between gap-2 px-4 py-2.5 text-sm text-text hover:bg-surface/50"
                  >
                    <span className="min-w-0 flex-1 truncate">{a.title}</span>
                    {a.deadline_at && (
                      <span className="shrink-0 text-xs text-text3">
                        до{' '}
                        {new Date(a.deadline_at).toLocaleDateString('ru-RU', {
                          day: 'numeric',
                          month: 'short',
                        })}
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}

        {data && data.surveys.length > 0 && (
          <div>
            <SectionTitle icon={ClipboardList}>Активные опросы</SectionTitle>
            <ul className="divide-y divide-glass-border rounded-xl border border-glass-border bg-glass">
              {data.surveys.map((s) => (
                <li key={s.id}>
                  <Link
                    to={`/learn/surveys?s=${s.id}`}
                    className="flex items-center justify-between gap-2 px-4 py-2.5 text-sm text-text hover:bg-surface/50"
                  >
                    <span className="min-w-0 flex-1 truncate">{s.title}</span>
                    {s.closes_at && (
                      <span className="shrink-0 text-xs text-text3">
                        до{' '}
                        {new Date(s.closes_at).toLocaleDateString('ru-RU', {
                          day: 'numeric',
                          month: 'short',
                        })}
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}

        {data && data.novelties.length > 0 && (
          <div>
            <SectionTitle icon={Sparkles}>Новинки</SectionTitle>
            <ul className="divide-y divide-glass-border rounded-xl border border-glass-border bg-glass">
              {data.novelties.map((n) => (
                <li key={`${n.object_type}-${n.object_id}`}>
                  <Link
                    to={n.url_path}
                    className="block px-4 py-2.5 text-sm text-text hover:bg-surface/50"
                  >
                    {n.title}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}

        {(recent.data?.length ?? 0) > 0 && (
          <div>
            <SectionTitle icon={Clock}>Недавнее</SectionTitle>
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
