import {
  AlarmClock,
  AlarmClockOff,
  BellOff,
  CalendarClock,
  ChevronRight,
  Plus,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import { DATE_CHIP } from '@/components/task/DateTimeEditor'
import { Button } from '@/components/ui/Button'
import { DateField } from '@/components/ui/DateField'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { PropertyRow } from '@/components/ui/PropertyRows'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import {
  useCreateReminder,
  useDeleteReminder,
  useTaskReminders,
  useTaskUpdatePending,
} from '@/hooks/useTaskReminders'
import { cn } from '@/lib/cn'
import {
  addDaysKey,
  dayKey,
  dayTimeToIso,
  formatDueLong,
  timeKey,
  todayKey,
} from '@/lib/taskDates'
import {
  deliveryHint,
  momentHint,
  momentText,
  reminderAddBlock,
  reminderBlockLabel,
  reminderBlockText,
  type ReminderCreateBody,
  type ReminderPreset,
  reminderLabel,
  reminderPresets,
  reminderStatus,
  type TaskReminderItem,
  timezoneNote,
} from '@/lib/taskReminders'
import { type Task } from '@/lib/tasks'

const MINUTE = 60_000

interface Props {
  task: Task
  /** Раскладка карточки, замороженная при открытии (`TaskDetailDrawer`). */
  desktop: boolean
  /** Уйти в «Настройки → Уведомления»: карточка закрывается сама, маршрут —
   *  тиком позже (иначе модальный Radix оставляет `pointer-events:none`). */
  onOpenSettings: () => void
}

/**
 * «Напомнить» в карточке задачи (0062): личные напоминания — только себе.
 *
 * Строку видит любой, кто открыл карточку, включая viewer'а: это личная
 * настройка, как колокольчик «следить», а не правка задачи — гейт `readOnly`
 * тут отнял бы кнопку именно у исполнителей точек. Варианты считает
 * `lib/taskReminders.ts`, состояние каждой строки — сервер.
 *
 * Десктоп: меню ТОЛЬКО с вариантами, «Выбрать дату и время…» — отдельный
 * диалог: Radix-меню глушит Tab и перехватывает печать (typeahead), и поля
 * внутри него не работают. Телефон: строка свойств → шторка.
 */
export function ReminderControl({ task, desktop, onOpenSettings }: Props) {
  const reminders = useTaskReminders(task.id, true)
  const create = useCreateReminder(task.id)
  const remove = useDeleteReminder(task.id)
  const updating = useTaskUpdatePending(task.id)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [customOpen, setCustomOpen] = useState(false)

  const items = reminders.data?.items ?? []
  const hint = deliveryHint(reminders.data?.delivery)
  const block = reminderAddBlock(task, items)
  const canAdd = block === null
  const busy = updating || create.isPending
  const now = Date.now()
  const presets = canAdd ? reminderPresets(task, now, items) : []

  const add = (body: ReminderCreateBody, after?: () => void) =>
    create.mutate(body, { onSuccess: () => after?.() })

  const goSettings = () => {
    setSheetOpen(false)
    setCustomOpen(false)
    onOpenSettings()
  }

  const custom = (
    <CustomReminderDialog
      open={customOpen}
      onOpenChange={setCustomOpen}
      busy={busy}
      onSubmit={(fireAt) => add({ anchor: 'at', fire_at: fireAt }, () => setCustomOpen(false))}
    />
  )

  if (desktop) {
    return (
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {items.map((item) => (
          <ReminderChip
            key={item.id}
            item={item}
            now={now}
            onRemove={() => remove.mutate(item.id)}
          />
        ))}
        {canAdd && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              {/* Не «Ещё»: так уже называется меню действий в шапке карточки,
                  и скринридер слышал бы две одинаковые кнопки. */}
              <button
                type="button"
                disabled={busy}
                aria-label="Добавить напоминание"
                title={busy ? 'Сохраняем срок…' : undefined}
                className={cn(DATE_CHIP, 'gap-1 hover:text-text', busy && 'opacity-60')}
              >
                {items.length ? (
                  <Plus className="h-3.5 w-3.5" strokeWidth={1.9} />
                ) : (
                  <AlarmClock className="h-3.5 w-3.5" strokeWidth={1.9} />
                )}
                Напомнить
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-[300px]">
              <PresetGroups presets={presets} onPick={(p) => add(p.body)} />
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => setCustomOpen(true)} className="gap-2">
                <CalendarClock className="h-4 w-4 text-text2" strokeWidth={1.9} />
                Выбрать дату и время…
              </DropdownMenuItem>
              {hint && (
                <>
                  <DropdownMenuSeparator />
                  <DeliveryHintBlock text={hint} onOpenSettings={goSettings} menu />
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        {/* Причина словами, а не прочерк. У выполненной задачи с напоминаниями
            её уже несут сами чипы («не сработает — задача выполнена»). */}
        {block && (block === 'limit' || items.length === 0) && (
          <span className="text-[13px] text-text2">{reminderBlockLabel(block)}</span>
        )}
        {custom}
      </div>
    )
  }

  const first = items.find((i) => i.state === 'armed') ?? items[0]
  // Шторке есть что показать, только если есть свои напоминания или варианты.
  // Иначе строка — подпись с причиной, без стрелки: пустая шторка читалась
  // как поломка (ОС 24.09).
  const openable = items.length > 0 || canAdd
  return (
    <>
      <PropertyRow label="Напомнить" onClick={openable ? () => setSheetOpen(true) : undefined}>
        <span className={cn('flex min-w-0 items-center gap-1', first?.state !== 'armed' && 'text-text2')}>
          <span className="truncate">
            {first
              ? first.state === 'armed' && first.fire_at
                ? `${reminderLabel(first, now)} · ${momentHint(first.fire_at, now)}`
                : reminderLabel(first, now)
              : block
                ? reminderBlockLabel(block)
                : '—'}
          </span>
          {items.length > 1 && <span className="shrink-0 text-text2">+{items.length - 1}</span>}
          {openable && <ChevronRight className="h-4 w-4 shrink-0 text-text2" strokeWidth={1.9} />}
        </span>
      </PropertyRow>
      <ResponsiveDialog
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        title="Напомнить"
        description={sheetSubtitle(task)}
        dismissLabel="Готово"
      >
        {items.length > 0 && (
          <section className="flex flex-col gap-2">
            <SheetLabel>Мои напоминания</SheetLabel>
            <div className="overflow-hidden rounded-[14px] border border-glass-border bg-tint">
              {items.map((item) => (
                <div
                  key={item.id}
                  className="flex min-h-[52px] items-center gap-3 border-t border-hair px-3.5 first:border-t-0"
                >
                  <ReminderIcon item={item} />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-[15px] text-text">{reminderLabel(item, now)}</span>
                    <span className="text-[13px] text-text2">{reminderStatus(item, now)}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => remove.mutate(item.id)}
                    className="min-h-11 shrink-0 px-2 text-[14px] text-text2 active:text-text"
                  >
                    Удалить
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}
        {canAdd && (
          <section className="flex flex-col gap-2">
            <SheetLabel>{items.length ? 'Напомнить ещё' : 'Когда напомнить'}</SheetLabel>
            <div className="overflow-hidden rounded-[14px] border border-glass-border bg-tint">
              {presets.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  disabled={busy}
                  onClick={() => add(p.body)}
                  className="flex min-h-[52px] w-full items-center gap-3 border-t border-hair px-3.5 text-left first:border-t-0 active:bg-glass disabled:opacity-60"
                >
                  <span className="flex-1 text-[16px] text-text">{p.label}</span>
                  <span className="text-[15px] tabular-nums text-text2">{p.hint}</span>
                </button>
              ))}
              <button
                type="button"
                onClick={() => setCustomOpen(true)}
                className="flex min-h-[52px] w-full items-center gap-3 border-t border-hair px-3.5 text-left first:border-t-0 active:bg-glass"
              >
                <span className="flex-1 text-[16px] text-text">Выбрать дату и время…</span>
                <ChevronRight className="h-4 w-4 text-text2" strokeWidth={1.9} />
              </button>
            </div>
          </section>
        )}
        {block && <SheetNote text={reminderBlockText(block)} />}
        {/* Куда придёт — вопрос, только пока что-то может прийти. */}
        {hint && block !== 'done' && <DeliveryHintBlock text={hint} onOpenSettings={goSettings} />}
      </ResponsiveDialog>
      {custom}
    </>
  )
}

function sheetSubtitle(task: Task): string {
  const due = task.due_at ? ` · срок ${formatDueLong(task.due_at, task.due_has_time)}` : ''
  return `«${task.title}»${due}`
}

function SheetLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[12px] font-bold uppercase tracking-[0.07em] text-text2">{children}</span>
  )
}

function SheetNote({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-[14px] border border-glass-border bg-tint px-3.5 py-3 text-[14px] text-text2">
      <AlarmClockOff className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.9} />
      <span>{text}</span>
    </div>
  )
}

function ReminderIcon({ item }: { item: TaskReminderItem }) {
  if (item.state === 'armed') {
    return <AlarmClock className="h-5 w-5 shrink-0 text-amber" strokeWidth={1.9} />
  }
  if (item.state === 'fired') {
    return <AlarmClock className="h-5 w-5 shrink-0 text-text2" strokeWidth={1.9} />
  }
  return <AlarmClockOff className="h-5 w-5 shrink-0 text-text2" strokeWidth={1.9} />
}

function ReminderChip({
  item,
  now,
  onRemove,
}: {
  item: TaskReminderItem
  now: number
  onRemove: () => void
}) {
  const armed = item.state === 'armed'
  const label = reminderLabel(item, now)
  const text =
    armed && item.fire_at && item.anchor !== 'at'
      ? `${label} · ${momentHint(item.fire_at, now)}`
      : armed
        ? label
        : `${label} — ${reminderStatus(item, now)}`
  return (
    <span
      className={cn(
        DATE_CHIP,
        'max-w-full gap-1 pr-0.5',
        armed
          ? 'bg-amber/15 text-text shadow-[inset_0_0_0_1px_color-mix(in_srgb,rgb(var(--amber))_45%,transparent)]'
          : 'text-text2',
      )}
      title={armed ? undefined : reminderStatus(item, now)}
    >
      {armed ? (
        <AlarmClock className="h-3.5 w-3.5 shrink-0 text-amber" strokeWidth={1.9} />
      ) : (
        <AlarmClockOff className="h-3.5 w-3.5 shrink-0" strokeWidth={1.9} />
      )}
      <span className="min-w-0 truncate">{text}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Удалить напоминание: ${label}`}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-text2 hover:bg-glass hover:text-text"
      >
        <X className="h-3 w-3" strokeWidth={2} />
      </button>
    </span>
  )
}

function PresetGroups({
  presets,
  onPick,
}: {
  presets: ReminderPreset[]
  onPick: (p: ReminderPreset) => void
}) {
  const groups: { key: ReminderPreset['group']; title: string }[] = [
    { key: 'deadline', title: 'От срока' },
    { key: 'time', title: 'Время' },
  ]
  return (
    <>
      {groups.map(({ key, title }) => {
        const list = presets.filter((p) => p.group === key)
        if (list.length === 0) return null
        return (
          <div key={key}>
            <DropdownMenuLabel className="text-[11px] font-bold uppercase tracking-[0.07em] text-text2">
              {title}
            </DropdownMenuLabel>
            {list.map((p) => (
              <DropdownMenuItem key={p.key} onSelect={() => onPick(p)} className="gap-3">
                <span className="flex-1">{p.label}</span>
                <span className="tabular-nums text-text2">{p.hint}</span>
              </DropdownMenuItem>
            ))}
          </div>
        )
      })}
    </>
  )
}

function DeliveryHintBlock({
  text,
  onOpenSettings,
  menu = false,
}: {
  text: string
  onOpenSettings: () => void
  menu?: boolean
}) {
  const link = (
    <span className="mt-1 block font-semibold text-amber">Включить уведомления →</span>
  )
  if (menu) {
    // Ссылка — пункт меню: Radix закрывает меню, маршрут меняет вызывающий.
    return (
      <DropdownMenuItem onSelect={onOpenSettings} className="items-start gap-2 text-[12px] text-text2">
        <BellOff className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={1.9} />
        <span>
          {text}
          {link}
        </span>
      </DropdownMenuItem>
    )
  }
  return (
    <div className="flex items-start gap-2 rounded-[14px] border border-glass-border bg-tint px-3.5 py-3 text-[14px] text-text2">
      <BellOff className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.9} />
      <span>
        {text}
        <button type="button" onClick={onOpenSettings} className="block min-h-11 text-left">
          {link}
        </button>
      </span>
    </div>
  )
}

function CustomReminderDialog({
  open,
  onOpenChange,
  busy,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  busy: boolean
  onSubmit: (fireAt: string) => void
}) {
  const [day, setDay] = useState('')
  const [time, setTime] = useState('')
  const now = Date.now()
  // Открывают диалог и снаружи (пункт меню, строка шторки) — значения по
  // умолчанию ставим по факту открытия: ближайший целый час.
  useEffect(() => {
    if (!open) return
    const next = Math.ceil((Date.now() + MINUTE) / (60 * MINUTE)) * 60 * MINUTE
    setDay(dayKey(next))
    setTime(timeKey(next))
  }, [open])
  const fireAt = day && time ? dayTimeToIso(day, time) : null
  const past = fireAt !== null && Date.parse(fireAt) <= now + MINUTE
  const tooFar = fireAt !== null && day > addDaysKey(todayKey(now), 366)
  const note = timezoneNote(now)
  const valid = fireAt !== null && !past && !tooFar
  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Своё время"
      desktopWidth={420}
      footer={
        <Button disabled={!valid || busy} onClick={() => fireAt && onSubmit(fireAt)}>
          {valid && fireAt ? `Напомнить ${momentText(fireAt, now)}` : 'Напомнить'}
        </Button>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1.5 text-[13px] text-text2">
          Дата
          <DateField value={day} onChange={setDay} ariaLabel="Дата напоминания" className="h-11" />
        </label>
        <label className="flex flex-col gap-1.5 text-[13px] text-text2">
          Время
          <DateField
            type="time"
            value={time}
            onChange={setTime}
            ariaLabel="Время напоминания"
            className="h-11"
          />
        </label>
      </div>
      {past && <p className="text-[13px] text-red">Это время уже прошло.</p>}
      {tooFar && <p className="text-[13px] text-red">Не дальше чем на год вперёд.</p>}
      {note && <p className="text-[13px] text-text2">{note}.</p>}
    </ResponsiveDialog>
  )
}
