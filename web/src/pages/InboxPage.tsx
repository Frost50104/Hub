import {
  AlarmClock,
  AtSign,
  Bell,
  BookOpen,
  CalendarClock,
  Check,
  CheckCircle2,
  CheckSquare,
  Flag,
  MessageSquare,
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
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
  useSetReadState,
  useUnreadCount,
} from '@/hooks/useNotifications'
import { invalidateTaskThread } from '@/hooks/useThreads'
import { cn } from '@/lib/cn'
import { bucketByAge, flattenPages } from '@/lib/inboxPaging'
import {
  allIds,
  pruneSelection,
  selectAllLabel,
  selectionLabel,
  toggleId,
} from '@/lib/inboxSelection'
import { inboxCounter, inboxEmpty } from '@/lib/inboxView'
import { type Notification } from '@/lib/notifications'
import { taskIdFromHref } from '@/lib/taskLinks'
import { useResolvedSpace } from '@/lib/workspace'

const KIND_ICON: Record<string, typeof Bell> = {
  'task.assigned_to_me': CheckSquare,
  'task.mentioned': AtSign,
  'task.commented_on_watched': MessageSquare,
  'task.status_changed_on_watched': CheckCircle2,
  'task.due_soon': CalendarClock,
  'task.overdue': CalendarClock,
  'task.reminder': AlarmClock,
  'race.started': Flag,
  'race.record': Flag,
  'race.push_reminder': Bell,
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
  'task.reminder': 'bg-amber text-on-amber',
  'race.started': 'bg-amber text-on-amber',
  'race.record': 'bg-green-deep text-bg',
  'race.push_reminder': 'bg-amber text-on-amber',
}

const DEFAULT_TONE = 'bg-surface text-text2'

export function InboxPage() {
  const isDesktop = useIsDesktop()
  return isDesktop ? <DesktopInbox /> : <MobileInbox />
}

/** Режим выбора: состояние и действия панели, одно на обе раскладки. */
interface Selection {
  selecting: boolean
  selected: ReadonlySet<number>
  allSelected: boolean
  pending: boolean
  start: () => void
  exit: () => void
  toggle: (id: number) => void
  toggleAll: () => void
  apply: (isRead: boolean) => void
}

function useInbox() {
  // Чип — выбор одного из двух окон выборки (unread_only на сервере), а не
  // декоративная вкладка: клик по уже активному ничего не меняет.
  //
  // Открываемся на «Непрочитанных» (31.08, решение владельца): «Входящие» — это
  // список дел, а не архив, и у активного пользователя прочитанное измеряется
  // сотнями. Состояние локальное и живёт до ухода со страницы: это ДЕФОЛТ, а не
  // сохранённая настройка — вернувшись, человек снова видит то, что не разобрал.
  const [unreadOnly, setUnreadOnlyState] = useState(true)
  const notifications = useNotifications(unreadOnly)
  const markAll = useMarkAllRead()
  const markOne = useMarkRead()
  const setReadState = useSetReadState()
  const qc = useQueryClient()
  // Переход из уведомления обязан показать СВЕЖЕЕ обсуждение: карточка
  // монтируется заново, но обсуждение моложе 30 с (`staleTime`) берётся из
  // кэша, и только что пришедший комментарий в нём отсутствует (ОС 08.09).
  // Прочитанная строка — тоже переход, поэтому инвалидация вне условия.
  const openNotification = (n: Notification) => {
    const taskId = taskIdFromHref(n.url)
    if (taskId) void invalidateTaskThread(qc, taskId)
    if (!n.is_read) markOne.mutate(n.id)
  }
  // Страницы склеиваются в один список (дедуп по id — `lib/inboxPaging.ts`).
  // useMemo на данных запроса, а не на `?? []`: литерал даёт новую ссылку
  // каждый рендер, и группировка пересчитывалась бы вхолостую.
  const items = useMemo(
    () => flattenPages(notifications.data?.pages ?? []),
    [notifications.data],
  )
  // Число непрочитанных — из того же источника, что бейдж в сайдбаре, а НЕ из
  // длины списка: список постраничный, и у человека со 160 непрочитанными
  // подпись говорила бы «50 непрочитанных». Ключ запроса общий с бейджем, так
  // что лишнего похода в сеть нет, а мутации инвалидируют весь префикс
  // `['notifications']` — число обновляется само.
  const unreadCount = useUnreadCount()
  const unread = unreadCount.data?.count ?? items.filter((n) => !n.is_read).length
  const groups = useMemo(() => bucketByAge(items, Date.now()), [items])

  // Режим выбора (19.10): вход кнопкой «Выбрать», выбор — локальное множество
  // id. `selected` — ПРОИЗВОДНОЕ от `picked` и загруженного: строки, ушедшие
  // при фоновом перезапросе (прочитаны с другого устройства), выпадают сами, и
  // серверу их id не уходят (`pruneSelection`).
  const [selecting, setSelecting] = useState(false)
  const [picked, setPicked] = useState<ReadonlySet<number>>(() => new Set())
  const selected = useMemo(() => pruneSelection(picked, items), [picked, items])
  const allSelected = items.length > 0 && selected.size === items.length
  const exitSelection = useCallback(() => {
    setSelecting(false)
    setPicked(new Set())
  }, [])
  // Смена окна выборки сбрасывает выбор: id «Всех» и «Непрочитанных» — разные
  // множества, и слать серверу выбор из другого окна нельзя.
  const setUnreadOnly = (next: boolean) => {
    if (next === unreadOnly) return
    exitSelection()
    setUnreadOnlyState(next)
  }
  const selection: Selection = {
    selecting,
    selected,
    allSelected,
    pending: setReadState.isPending,
    start: () => setSelecting(true),
    exit: exitSelection,
    toggle: (id) => setPicked((prev) => toggleId(prev, id)),
    // «Выбрать все» = все ЗАГРУЖЕННЫЕ; число в подписи кнопки это и говорит.
    toggleAll: () => setPicked(allSelected ? new Set() : allIds(items)),
    apply: (isRead) => {
      if (selected.size === 0) return
      setReadState.mutate({ ids: [...selected], is_read: isRead }, { onSuccess: exitSelection })
    },
  }
  return {
    notifications,
    markAll,
    openNotification,
    items,
    unread,
    groups,
    unreadOnly,
    setUnreadOnly,
    selection,
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

/**
 * Полоса «Все / Непрочитанные» + счётчик.
 *
 * Одна на обе раскладки. На телефоне чипов раньше не было (так был нарисован
 * макет), и пока список по умолчанию показывал ВСЁ, это ничего не стоило.
 * С дефолтом «Непрочитанные» их отсутствие означало бы, что прочитанное с
 * телефона недостижимо вовсе, — поэтому чипы переехали в общий компонент.
 */
function InboxFilters({
  unreadOnly,
  onChange,
  unread,
  className,
}: {
  unreadOnly: boolean
  onChange: (v: boolean) => void
  unread: number
  className?: string
}) {
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <FilterChip active={!unreadOnly} onClick={() => onChange(false)}>
        Все
      </FilterChip>
      <FilterChip active={unreadOnly} onClick={() => onChange(true)}>
        Непрочитанные
      </FilterChip>
      {/* Ветвление и причина, по которой дроби «N из M» здесь нет, —
          в `lib/inboxView.ts`, там же тест. */}
      <span className="ml-auto text-[13px] text-text2">{inboxCounter(unread)}</span>
    </div>
  )
}

const ROW_CLASS =
  'flex w-full items-start gap-3 border-b border-hair px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber'

function NotificationRow({
  notification,
  onOpen,
  selectable,
  selected,
  onToggle,
}: {
  notification: Notification
  onOpen: () => void
  selectable: boolean
  selected: boolean
  onToggle: () => void
}) {
  const Icon = KIND_ICON[notification.kind] ?? (notification.kind.startsWith('task.') ? Bell : BookOpen)
  const tone = KIND_TONE[notification.kind] ?? DEFAULT_TONE
  const unread = !notification.is_read

  const content = (
    <>
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
    </>
  )

  if (selectable) {
    // В режиме выбора строка — чекбокс, а не ссылка: тап выбирает, не открывает.
    // Элемент другой (`<button>`), классы, раскладка и дети те же; слева —
    // квадрат-чекбокс по образцу `CustomFieldEditor`, выбранная строка — рамка
    // амбером внутрь, как у выделенной задачи (`ui/ListRow`).
    return (
      <button
        type="button"
        role="checkbox"
        aria-checked={selected}
        onClick={onToggle}
        className={cn(
          ROW_CLASS,
          selected && 'bg-surface shadow-[inset_0_0_0_1px_rgb(var(--amber))]',
        )}
      >
        <span
          aria-hidden
          className={cn(
            'mt-1.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border border-glass-border',
            selected ? 'bg-amber text-on-amber' : 'bg-glass text-transparent',
          )}
        >
          <Check className="h-3.5 w-3.5" />
        </span>
        {content}
      </button>
    )
  }

  return (
    <Link to={notification.url ?? '#'} onClick={onOpen} className={ROW_CLASS}>
      {content}
    </Link>
  )
}

/**
 * Панель режима выбора. На десктопе липнет под чипами (скролл-порт — `<main>`),
 * на телефоне — фиксированная полоса над таб-баром, порталом в `body`: `.glass`
 * с `backdrop-filter` делает containing block для `position: fixed`, и внутри
 * стеклянной панели полоса встала бы не там (образец — `MobileViewControlBar`).
 * Подложка непрозрачная — в светлой теме стекло просвечивало бы список.
 */
function SelectionBar({
  selection,
  loaded,
  mobile,
}: {
  selection: Selection
  loaded: number
  mobile: boolean
}) {
  const count = selection.selected.size
  const disabled = count === 0 || selection.pending
  const label = (
    <span className="text-[13px] font-semibold text-text">{selectionLabel(count)}</span>
  )
  const all = (
    <button
      type="button"
      onClick={selection.toggleAll}
      disabled={loaded === 0}
      className={cn(
        'text-[13px] font-semibold text-text2 hover:text-text',
        mobile ? 'min-h-11 px-2' : 'min-h-8',
      )}
    >
      {selectAllLabel(loaded, selection.allSelected)}
    </button>
  )

  if (!mobile) {
    return (
      <div
        className="sticky z-10 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[12px] border border-glass-border bg-bg-alt px-3 py-2"
        style={{ top: 'var(--safe-top, 0px)' }}
      >
        {label}
        {all}
        <div className="ml-auto flex items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={disabled}
            onClick={() => selection.apply(true)}
          >
            Прочитано
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={disabled}
            onClick={() => selection.apply(false)}
          >
            Непрочитано
          </Button>
          <Button size="sm" variant="ghost" onClick={selection.exit}>
            Отмена
          </Button>
        </div>
      </div>
    )
  }

  if (typeof document === 'undefined') return null
  return createPortal(
    <div
      className="fixed inset-x-0 z-30 border-t border-glass-border px-4 pb-2 pt-1 lg:hidden"
      style={{
        // Таб-бар — 56px + свой safe-area; панель садится ровно на него.
        bottom: 'calc(env(safe-area-inset-bottom, 0px) + 3.5rem)',
        background: 'color-mix(in srgb, rgb(var(--bg-alt)) 95%, transparent)',
      }}
    >
      <div className="-mr-2 flex items-center justify-between">
        {label}
        {all}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Button
          size="lg"
          variant="secondary"
          className="min-h-11 px-2"
          disabled={disabled}
          onClick={() => selection.apply(true)}
        >
          Прочитано
        </Button>
        <Button
          size="lg"
          variant="secondary"
          className="min-h-11 px-2"
          disabled={disabled}
          onClick={() => selection.apply(false)}
        >
          Непрочитано
        </Button>
        <Button size="lg" variant="ghost" className="min-h-11 px-2" onClick={selection.exit}>
          Отмена
        </Button>
      </div>
    </div>,
    document.body,
  )
}

/**
 * «Показать ещё» — страницы по 50 (`lib/inboxPaging.ts`). Ошибка ДОГРУЗКИ —
 * компактно на месте кнопки, а не вместо всего списка: уже показанное остаётся.
 */
function LoadMore({
  query,
  className,
}: {
  query: ReturnType<typeof useNotifications>
  className?: string
}) {
  if (query.isFetchNextPageError) {
    return (
      <QueryError
        error={query.error}
        onRetry={() => void query.fetchNextPage()}
        title="Не удалось загрузить ещё"
        className={className}
      />
    )
  }
  if (!query.hasNextPage) return null
  return (
    <div className={className}>
      {/* `disabled` на ЛЮБОМ `isFetching`, не только на догрузке: `fetchNextPage`
          обрывает фоновый перезапрос и взял бы курсор из устаревшей страницы. */}
      <button
        type="button"
        onClick={() => void query.fetchNextPage()}
        disabled={query.isFetching}
        className="inline-flex h-11 w-full items-center justify-center rounded-xl border border-hair text-sm font-semibold text-text2 hover:text-text disabled:opacity-60"
      >
        {query.isFetchingNextPage ? 'Загружаем…' : 'Показать ещё'}
      </button>
    </div>
  )
}

function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="m-0 border-b border-hair bg-tint px-4 py-2 text-[12px] font-bold uppercase tracking-[0.07em] text-text2">
      {children}
    </p>
  )
}

/**
 * `unreadOnly` обязателен: с новым дефолтом «пусто» чаще всего значит «всё
 * разобрано», а не «уведомлений не было». Текст «Здесь пока тихо» человеку с
 * двумя сотнями прочитанных читался бы как потеря истории.
 */
function EmptyInbox({ unreadOnly }: { unreadOnly: boolean }) {
  const Glyph = unreadOnly ? CheckCircle2 : Bell
  const { title, body } = inboxEmpty(unreadOnly)
  return (
    <div className="mx-4 mt-6 flex flex-col items-center gap-2 rounded-2xl border border-glass-border bg-tint p-10 text-center">
      <Glyph className="h-10 w-10 text-text2" />
      <p className="font-display text-[18px] font-bold text-text">{title}</p>
      <p className="max-w-xs text-[15px] text-text2">{body}</p>
    </div>
  )
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

function NotificationGroups({
  groups,
  selection,
  onOpen,
}: {
  groups: ReturnType<typeof bucketByAge<Notification>>
  selection: Selection
  onOpen: (n: Notification) => void
}) {
  return (
    <>
      {groups.map(
        (g) =>
          g.items.length > 0 && (
            <section key={g.key}>
              <GroupLabel>{g.label}</GroupLabel>
              {g.items.map((n) => (
                <NotificationRow
                  key={n.id}
                  notification={n}
                  onOpen={() => onOpen(n)}
                  selectable={selection.selecting}
                  selected={selection.selected.has(n.id)}
                  onToggle={() => selection.toggle(n.id)}
                />
              ))}
            </section>
          ),
      )}
    </>
  )
}

// ─── Десктоп ────────────────────────────────────────────────────────────────

function DesktopInbox() {
  const {
    notifications,
    markAll,
    openNotification,
    items,
    unread,
    groups,
    unreadOnly,
    setUnreadOnly,
    selection,
  } = useInbox()

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
        <div className="flex items-center gap-2">
          {items.length > 0 && !selection.selecting && (
            <Button size="sm" variant="ghost" onClick={selection.start}>
              Выбрать
            </Button>
          )}
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
        </div>
      </header>

      <InboxFilters unreadOnly={unreadOnly} onChange={setUnreadOnly} unread={unread} />
      {selection.selecting && (
        <SelectionBar selection={selection} loaded={items.length} mobile={false} />
      )}

      {notifications.isLoading && <SkeletonRows rows={5} />}
      {notifications.isError && !notifications.isFetchNextPageError && (
        <QueryError
          error={notifications.error}
          onRetry={() => void notifications.refetch()}
          title="Не удалось загрузить уведомления"
        />
      )}
      {notifications.data && items.length === 0 && (
        <EmptyInbox unreadOnly={unreadOnly} />
      )}

      {items.length > 0 && (
        <div className="overflow-hidden rounded-[14px] border border-glass-border bg-tint">
          <NotificationGroups groups={groups} selection={selection} onOpen={openNotification} />
          <LoadMore query={notifications} className="p-3" />
        </div>
      )}
    </div>
  )
}

// ─── Мобильный ──────────────────────────────────────────────────────────────

function HeaderAction({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex min-h-11 items-center px-2.5 text-[15px] font-semibold text-text active:opacity-70 disabled:opacity-50"
    >
      {children}
    </button>
  )
}

function MobileInbox() {
  const {
    notifications,
    markAll,
    openNotification,
    items,
    unread,
    groups,
    unreadOnly,
    setUnreadOnly,
    selection,
  } = useInbox()
  const space = useResolvedSpace()

  let trailing: React.ReactNode
  if (selection.selecting) {
    trailing = (
      <div className="-mr-2.5 flex items-center">
        <HeaderAction onClick={selection.exit}>Отмена</HeaderAction>
      </div>
    )
  } else if (items.length > 0 || unread > 0) {
    trailing = (
      <div className="-mr-2.5 flex items-center">
        {items.length > 0 && <HeaderAction onClick={selection.start}>Выбрать</HeaderAction>}
        {unread > 0 && (
          <HeaderAction onClick={() => markAll.mutate()} disabled={markAll.isPending}>
            Прочитать всё
          </HeaderAction>
        )}
      </div>
    )
  }

  return (
    <>
      <MobilePageHeader title="Входящие" trailing={trailing} />

      {/* Чипы появились и здесь (31.08). Прежде их не было по макету, и это
          было безобидно, пока список открывался на «Все»; с дефолтом
          «Непрочитанные» без них прочитанное с телефона было бы недостижимо. */}
      <InboxFilters
        unreadOnly={unreadOnly}
        onChange={setUnreadOnly}
        unread={unread}
        className="px-4 pb-2 pt-1"
      />

      {notifications.isLoading && <SkeletonRows rows={5} className="p-4" />}
      {notifications.isError && !notifications.isFetchNextPageError && (
        <QueryError
          error={notifications.error}
          onRetry={() => void notifications.refetch()}
          title="Не удалось загрузить уведомления"
          className="m-4"
        />
      )}
      {notifications.data && items.length === 0 && (
        <EmptyInbox unreadOnly={unreadOnly} />
      )}

      <NotificationGroups groups={groups} selection={selection} onOpen={openNotification} />
      <LoadMore query={notifications} className="px-4 py-3" />

      {/* Под фиксированной панелью выбора последняя строка иначе недостижима. */}
      {selection.selecting && <div aria-hidden className="h-28" />}
      {selection.selecting && (
        <SelectionBar selection={selection} loaded={items.length} mobile />
      )}

      {/* FAB «Создать» — задачный; из learn-пространства и из режима выбора его
          не показываем: он сидел бы на панели. */}
      {space === 'tasks' && !selection.selecting && <FloatingActionButton />}
    </>
  )
}
