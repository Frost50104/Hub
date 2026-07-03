import {
  AtSign,
  Bell,
  CalendarClock,
  CheckCircle2,
  CheckSquare,
  Loader2,
  MessageSquare,
} from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'

import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import {
  useMarkAllRead,
  useMarkRead,
  useNotifications,
} from '@/hooks/useNotifications'
import { cn } from '@/lib/cn'
import { type Notification } from '@/lib/notifications'

const KIND_ICON: Record<string, typeof Bell> = {
  'task.assigned_to_me': CheckSquare,
  'task.mentioned': AtSign,
  'task.commented_on_watched': MessageSquare,
  'task.status_changed_on_watched': CheckCircle2,
  'task.due_soon': CalendarClock,
  'task.overdue': CalendarClock,
}

const KIND_TONE: Record<string, string> = {
  'task.assigned_to_me': 'bg-amber/15 text-amber',
  'task.mentioned': 'bg-purple-500/15 text-purple-500',
  'task.commented_on_watched': 'bg-blue-500/15 text-blue-500',
  'task.status_changed_on_watched': 'bg-green/15 text-green',
  'task.due_soon': 'bg-amber/15 text-amber',
  'task.overdue': 'bg-red/15 text-red',
}

export function InboxPage() {
  const isDesktop = useIsDesktop()
  return isDesktop ? <DesktopInbox /> : <MobileInbox />
}

// ─── Mobile ─────────────────────────────────────────────────────────────────

function MobileInbox() {
  const notifications = useNotifications()
  const markAll = useMarkAllRead()
  const markOne = useMarkRead()

  const groups = useMemo(() => bucketByAge(notifications.data ?? []), [
    notifications.data,
  ])

  return (
    <>
      <MobilePageHeader
        title="Входящие"
        trailing={
          (notifications.data ?? []).some((n) => !n.is_read) ? (
            <button
              type="button"
              onClick={() => markAll.mutate()}
              className="text-xs text-amber active:opacity-70"
              disabled={markAll.isPending}
            >
              Прочитать всё
            </button>
          ) : undefined
        }
      />

      {notifications.isLoading && (
        <p className="flex items-center gap-2 px-4 py-4 text-sm text-text2">
          <Loader2 className="h-4 w-4 animate-spin" /> Загружаем…
        </p>
      )}
      {notifications.isError && (
        <QueryError
          error={notifications.error}
          onRetry={() => void notifications.refetch()}
          title="Не удалось загрузить уведомления"
          className="m-4"
        />
      )}
      {notifications.data && notifications.data.length === 0 && (
        <EmptyInbox />
      )}

      <div className="space-y-3 pb-3">
        {groups.map(
          (g) =>
            g.items.length > 0 && (
              <section key={g.key}>
                <h2 className="bg-bg-alt/70 px-4 py-1.5 text-[11px] uppercase tracking-wider text-text3">
                  {g.label}
                </h2>
                <ul>
                  {g.items.map((n) => (
                    <li key={n.id}>
                      <NotificationCard
                        notification={n}
                        onRead={() => {
                          if (!n.is_read) markOne.mutate(n.id)
                        }}
                      />
                    </li>
                  ))}
                </ul>
              </section>
            ),
        )}
      </div>

      <FloatingActionButton />
    </>
  )
}

function NotificationCard({
  notification,
  onRead,
}: {
  notification: Notification
  onRead: () => void
}) {
  const Icon = KIND_ICON[notification.kind] ?? Bell
  const tone = KIND_TONE[notification.kind] ?? 'bg-glass text-text2'
  const href = notification.url ?? '#'

  return (
    <Link
      to={href}
      onClick={onRead}
      className="flex items-start gap-3 border-b border-glass-border/60 px-4 py-3 active:bg-glass"
    >
      <span
        className={cn(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
          tone,
        )}
      >
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            'truncate text-sm font-medium',
            notification.is_read ? 'text-text2' : 'text-text',
          )}
        >
          {notification.title}
        </p>
        <p className="line-clamp-2 text-xs text-text3">{notification.body}</p>
        <p className="mt-0.5 text-[10px] text-text3">
          {formatRelative(notification.created_at)}
        </p>
      </div>
      {!notification.is_read && (
        <span className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full bg-amber" />
      )}
    </Link>
  )
}

function EmptyInbox() {
  return (
    <div className="mx-4 mt-6 flex flex-col items-center gap-2 rounded-2xl border border-glass-border bg-bg-alt/60 p-10 text-center">
      <Bell className="h-10 w-10 text-text3" />
      <p className="font-display text-base font-semibold text-text">
        Здесь пока тихо
      </p>
      <p className="max-w-xs text-sm text-text2">
        Назначения, упоминания, комментарии и дедлайны попадут сюда.
      </p>
    </div>
  )
}

function bucketByAge(items: Notification[]) {
  const now = Date.now()
  const WEEK = 7 * 24 * 60 * 60 * 1000
  return [
    {
      key: '7d',
      label: 'Последние 7 дней',
      items: items.filter(
        (n) => now - new Date(n.created_at).getTime() <= WEEK,
      ),
    },
    {
      key: 'older',
      label: 'Раньше',
      items: items.filter(
        (n) => now - new Date(n.created_at).getTime() > WEEK,
      ),
    },
  ]
}

function formatRelative(iso: string): string {
  const now = Date.now()
  const t = new Date(iso).getTime()
  const diff = now - t
  const MIN = 60 * 1000
  const HOUR = 60 * MIN
  const DAY = 24 * HOUR
  if (diff < HOUR) return `${Math.max(1, Math.round(diff / MIN))} мин назад`
  if (diff < DAY) return `${Math.round(diff / HOUR)} ч назад`
  if (diff < 7 * DAY) return `${Math.round(diff / DAY)} дн назад`
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

// ─── Desktop ────────────────────────────────────────────────────────────────

function DesktopInbox() {
  const notifications = useNotifications()
  const markAll = useMarkAllRead()
  const markOne = useMarkRead()

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold">Входящие</h1>
          <p className="text-sm text-text2">
            Уведомления о задачах, упоминаниях и дедлайнах.
          </p>
        </div>
        {(notifications.data ?? []).some((n) => !n.is_read) && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => markAll.mutate()}
            disabled={markAll.isPending}
          >
            Прочитать всё
          </Button>
        )}
      </header>

      {notifications.isLoading && (
        <p className="text-sm text-text2">Загружаем…</p>
      )}
      {notifications.isError && (
        <QueryError
          error={notifications.error}
          onRetry={() => void notifications.refetch()}
          title="Не удалось загрузить уведомления"
        />
      )}
      {notifications.data && notifications.data.length === 0 && (
        <EmptyInbox />
      )}

      <ul className="space-y-1">
        {notifications.data?.map((n) => (
          <li key={n.id}>
            <NotificationCard
              notification={n}
              onRead={() => {
                if (!n.is_read) markOne.mutate(n.id)
              }}
            />
          </li>
        ))}
      </ul>
    </div>
  )
}
