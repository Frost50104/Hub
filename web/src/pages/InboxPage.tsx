import {
  AtSign,
  Bell,
  BookOpen,
  CalendarClock,
  CheckCircle2,
  CheckSquare,
  MessageSquare,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import {
  useMarkAllRead,
  useMarkRead,
  useNotifications,
} from '@/hooks/useNotifications'
import { cn } from '@/lib/cn'
import { type Notification } from '@/lib/notifications'
import { plural } from '@/lib/typography'
import { useResolvedSpace } from '@/lib/workspace'

const KIND_ICON: Record<string, typeof Bell> = {
  'task.assigned_to_me': CheckSquare,
  'task.mentioned': AtSign,
  'task.commented_on_watched': MessageSquare,
  'task.status_changed_on_watched': CheckCircle2,
  'task.due_soon': CalendarClock,
  'task.overdue': CalendarClock,
}

/**
 * Тон вида — ПЛОТНАЯ заливка и краска, а не цветной текст на цветном тинте:
 * amber-на-amber давал 1,7:1 в светлой теме. У амбера краска фиксированная
 * (`--on-amber`), у остальных `--bg` — она флипается вместе с темой.
 */
const KIND_TONE: Record<string, string> = {
  'task.assigned_to_me': 'bg-amber text-on-amber',
  'task.mentioned': 'bg-blue-deep text-bg',
  'task.commented_on_watched': 'bg-text2 text-bg',
  'task.status_changed_on_watched': 'bg-green-deep text-bg',
  'task.due_soon': 'bg-amber text-on-amber',
  'task.overdue': 'bg-red text-bg',
}

const DEFAULT_TONE = 'bg-surface text-text2'

export function InboxPage() {
  const isDesktop = useIsDesktop()
  return isDesktop ? <DesktopInbox /> : <MobileInbox />
}

function useInbox() {
  // Чип — выбор одного из двух окон выборки (unread_only на сервере), а не
  // декоративная вкладка: клик по уже активному ничего не меняет.
  const [unreadOnly, setUnreadOnly] = useState(false)
  const notifications = useNotifications(unreadOnly)
  const markAll = useMarkAllRead()
  const markOne = useMarkRead()
  // useMemo на данных запроса, а не на `data ?? []`: литерал даёт новую
  // ссылку каждый рендер, и группировка пересчитывалась бы вхолостую.
  const items = useMemo(() => notifications.data ?? [], [notifications.data])
  const unread = items.filter((n) => !n.is_read).length
  const groups = useMemo(() => bucketByAge(items), [items])
  return {
    notifications,
    markAll,
    markOne,
    items,
    unread,
    groups,
    unreadOnly,
    setUnreadOnly,
  }
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'inline-flex min-h-8 items-center rounded-lg border px-3 text-[13px] font-semibold transition-colors',
        active ? 'border-text2 text-text' : 'border-transparent text-text2 hover:text-text',
      )}
    >
      {children}
    </button>
  )
}

function NotificationRow({
  notification,
  onRead,
}: {
  notification: Notification
  onRead: () => void
}) {
  const Icon = KIND_ICON[notification.kind] ?? (notification.kind.startsWith('task.') ? Bell : BookOpen)
  const tone = KIND_TONE[notification.kind] ?? DEFAULT_TONE
  const unread = !notification.is_read

  return (
    <Link
      to={notification.url ?? '#'}
      onClick={onRead}
      className="flex w-full items-start gap-3 border-b border-hair px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber"
    >
      <span
        className={cn(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
          tone,
        )}
      >
        <Icon className="h-[17px] w-[17px]" strokeWidth={2} />
      </span>
      <span className="min-w-0 flex-1">
        {/* display:block обязателен: на инлайновом боксе overflow и
            text-overflow инертны, и длинная подпись уезжала без многоточия. */}
        <span
          className={cn(
            'block truncate text-[15px]',
            unread ? 'font-semibold text-text' : 'font-medium text-text2',
          )}
        >
          {notification.title}
        </span>
        {/* Клэмп по высоте: 1.45 × 14 × 2 = 40,6px. */}
        <span className="mt-0.5 block max-h-[41px] overflow-hidden text-[14px] leading-[1.45] text-text2">
          {notification.body}
        </span>
        <span className="mt-[3px] block text-[13px] text-text2">
          {formatRelative(notification.created_at)}
        </span>
      </span>
      {unread && (
        <span className="mt-1.5 block h-2 w-2 shrink-0 rounded-full bg-amber" />
      )}
    </Link>
  )
}

function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="m-0 border-b border-hair bg-tint px-4 py-2 text-[12px] font-bold uppercase tracking-[0.07em] text-text2">
      {children}
    </p>
  )
}

function EmptyInbox() {
  return (
    <div className="mx-4 mt-6 flex flex-col items-center gap-2 rounded-2xl border border-glass-border bg-tint p-10 text-center">
      <Bell className="h-10 w-10 text-text2" />
      <p className="font-display text-[18px] font-bold text-text">Здесь пока тихо</p>
      <p className="max-w-xs text-[15px] text-text2">
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
      items: items.filter((n) => now - new Date(n.created_at).getTime() <= WEEK),
    },
    {
      key: 'older',
      label: 'Раньше',
      items: items.filter((n) => now - new Date(n.created_at).getTime() > WEEK),
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

// ─── Десктоп ────────────────────────────────────────────────────────────────

function DesktopInbox() {
  const { notifications, markAll, markOne, items, unread, groups, unreadOnly, setUnreadOnly } =
    useInbox()

  return (
    <div className="mx-auto flex max-w-[800px] flex-col gap-[18px] px-6 pb-10 pt-7">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-[24px] font-bold leading-[1.2] text-text">
            Входящие
          </h1>
          <p className="mt-[5px] text-[15px] text-text2">
            Уведомления о задачах, упоминаниях и дедлайнах.
          </p>
        </div>
        {unread > 0 && (
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

      <div className="flex items-center gap-2">
        <FilterChip active={!unreadOnly} onClick={() => setUnreadOnly(false)}>
          Все
        </FilterChip>
        <FilterChip active={unreadOnly} onClick={() => setUnreadOnly(true)}>
          Непрочитанные
        </FilterChip>
        {/* Счётчик не повторяет заголовок пустого состояния — только число. */}
        <span className="ml-auto text-[13px] text-text2">
          {unread > 0
            ? `${unread} непрочитанных из ${items.length}`
            : plural(items.length, 'уведомление', 'уведомления', 'уведомлений')}
        </span>
      </div>

      {notifications.isLoading && <SkeletonRows rows={5} />}
      {notifications.isError && (
        <QueryError
          error={notifications.error}
          onRetry={() => void notifications.refetch()}
          title="Не удалось загрузить уведомления"
        />
      )}
      {notifications.data && items.length === 0 && <EmptyInbox />}

      {items.length > 0 && (
        <div className="overflow-hidden rounded-[14px] border border-glass-border bg-tint">
          {groups.map(
            (g) =>
              g.items.length > 0 && (
                <section key={g.key}>
                  <GroupLabel>{g.label}</GroupLabel>
                  {g.items.map((n) => (
                    <NotificationRow
                      key={n.id}
                      notification={n}
                      onRead={() => {
                        if (!n.is_read) markOne.mutate(n.id)
                      }}
                    />
                  ))}
                </section>
              ),
          )}
        </div>
      )}
    </div>
  )
}

// ─── Мобильный ──────────────────────────────────────────────────────────────

function MobileInbox() {
  const { notifications, markAll, markOne, items, unread, groups, unreadOnly, setUnreadOnly } =
    useInbox()
  const space = useResolvedSpace()

  return (
    <>
      <MobilePageHeader
        title="Входящие"
        trailing={
          unread > 0 ? (
            <button
              type="button"
              onClick={() => markAll.mutate()}
              disabled={markAll.isPending}
              className="-mx-2.5 inline-flex min-h-11 items-center px-2.5 text-[15px] font-semibold text-text active:opacity-70"
            >
              Прочитать всё
            </button>
          ) : undefined
        }
      />

      <div className="flex items-center gap-2 border-b border-hair px-4 py-2.5">
        <FilterChip active={!unreadOnly} onClick={() => setUnreadOnly(false)}>
          Все
        </FilterChip>
        <FilterChip active={unreadOnly} onClick={() => setUnreadOnly(true)}>
          Непрочитанные
        </FilterChip>
      </div>

      {notifications.isLoading && <SkeletonRows rows={5} className="p-4" />}
      {notifications.isError && (
        <QueryError
          error={notifications.error}
          onRetry={() => void notifications.refetch()}
          title="Не удалось загрузить уведомления"
          className="m-4"
        />
      )}
      {notifications.data && items.length === 0 && <EmptyInbox />}

      {groups.map(
        (g) =>
          g.items.length > 0 && (
            <section key={g.key}>
              <GroupLabel>{g.label}</GroupLabel>
              {g.items.map((n) => (
                <NotificationRow
                  key={n.id}
                  notification={n}
                  onRead={() => {
                    if (!n.is_read) markOne.mutate(n.id)
                  }}
                />
              ))}
            </section>
          ),
      )}

      {/* FAB «Создать» — задачный; из learn-пространства его не показываем. */}
      {space === 'tasks' && <FloatingActionButton />}
    </>
  )
}
