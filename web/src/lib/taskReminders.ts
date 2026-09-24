/**
 * Личные напоминания по задаче (0062) — варианты, тексты, подсказки.
 *
 * Правила срабатывания живут на СЕРВЕРЕ (`app/services/task_reminders.py`):
 * там взводится, засыпает и переезжает на копию повтора; состояние строки
 * (`state`) приходит готовым. Здесь — только то, что нужно, чтобы нарисовать
 * меню «Напомнить»: момент каждого варианта (зеркало `anchor_moment` —
 * `REMINDER_DAY_HOUR` меняется ПАРОЙ) и подписи.
 *
 * Чистый модуль (только `import type`): vitest бежит без jsdom.
 */

import { addDaysKey, dayKey, dayTimeToIso, timeKey } from '@/lib/taskDates'
import type { Task } from '@/lib/tasks'

export type ReminderAnchor = 'at' | 'due' | 'due_day' | 'start' | 'start_day'
export type ReminderState = 'armed' | 'fired' | 'no_date' | 'passed' | 'done' | 'archived'

export interface TaskReminderItem {
  id: string
  anchor: ReminderAnchor
  offset_minutes: number
  /** Когда придёт (взведено); null — сработало или «спит». */
  fire_at: string | null
  state: ReminderState
  /** Сработавшее правило — когда пришло. */
  fired_at?: string | null
}

export interface ReminderDelivery {
  push_devices: number
  push_on: boolean
  inapp_on: boolean
}

export interface TaskRemindersResponse {
  items: TaskReminderItem[]
  delivery: ReminderDelivery
}

export interface ReminderCreateBody {
  anchor: ReminderAnchor
  offset_minutes?: number
  fire_at?: string
}

/** Зеркало сервера: срок без времени и якоря `*_day` — 09:00 display tz. */
export const REMINDER_DAY_HOUR = '09:00'

/** Потолок строк на задачу у человека — зеркало `MAX_PER_TASK`. */
export const MAX_REMINDERS_PER_TASK = 5

type TaskDates = Pick<Task, 'due_at' | 'due_has_time' | 'start_at' | 'start_has_time'>

/** Момент якоря (ISO) — зеркало `anchor_moment` сервера. */
export function anchorMoment(anchor: ReminderAnchor, task: TaskDates): string | null {
  const isDue = anchor === 'due' || anchor === 'due_day'
  const at = isDue ? task.due_at : anchor === 'at' ? null : task.start_at
  if (!at) return null
  const hasTime = isDue ? task.due_has_time : task.start_has_time
  if ((anchor === 'due' || anchor === 'start') && hasTime) return at
  return dayTimeToIso(dayKey(at), REMINDER_DAY_HOUR)
}

export interface ReminderPreset {
  key: string
  label: string
  /** Момент справа: «30.09 14:00» или «16:42», если сегодня. */
  hint: string
  group: 'deadline' | 'time'
  body: ReminderCreateBody
  fireAt: string
}

const MINUTE = 60_000

/** «30.09 14:00», а сегодняшний момент — просто «14:00». */
export function momentHint(iso: string, now: number): string {
  const key = dayKey(iso)
  const [, mm, dd] = key.split('-') as [string, string, string]
  return key === dayKey(now) ? timeKey(iso) : `${dd}.${mm} ${timeKey(iso)}`
}

/** «30.09 в 14:00» / «сегодня в 14:00» / «завтра в 9:00» — для тоста и строк. */
export function momentText(iso: string, now: number): string {
  const key = dayKey(iso)
  const today = dayKey(now)
  const time = timeKey(iso)
  if (key === today) return `сегодня в ${time}`
  if (key === addDaysKey(today, 1)) return `завтра в ${time}`
  const [, mm, dd] = key.split('-') as [string, string, string]
  return `${dd}.${mm} в ${time}`
}

function minuteIso(ms: number): string {
  return new Date(Math.floor(ms / MINUTE) * MINUTE).toISOString()
}

function relative(
  key: string,
  label: string,
  anchor: ReminderAnchor,
  offset: number,
  task: TaskDates,
): Omit<ReminderPreset, 'hint'> | null {
  const base = anchorMoment(anchor, task)
  if (!base) return null
  const fireAt = new Date(Date.parse(base) - offset * MINUTE).toISOString()
  return { key, label, group: 'deadline', body: { anchor, offset_minutes: offset }, fireAt }
}

/**
 * Варианты меню «Напомнить» по задаче и текущему моменту.
 *
 * Скрываются: прошедшие (и наступающие в ближайшую минуту — POST ответил бы
 * 422), уже поставленные, а также совпадающие по моменту с вариантом выше
 * («Завтра утром · 9:00» рядом с «Накануне · 9:00»): два пункта про одно и то же
 * время читаются как ошибка.
 */
export function reminderPresets(
  task: TaskDates,
  now: number,
  existing: readonly TaskReminderItem[] = [],
): ReminderPreset[] {
  const out: Omit<ReminderPreset, 'hint'>[] = []
  const push = (p: Omit<ReminderPreset, 'hint'> | null) => {
    if (p) out.push(p)
  }
  if (task.due_at && task.due_has_time) {
    push(relative('due:0', 'К сроку', 'due', 0, task))
    push(relative('due:15', 'За 15 минут', 'due', 15, task))
    push(relative('due:60', 'За 1 час', 'due', 60, task))
    push(relative('due:1440', 'За 1 день', 'due', 1440, task))
    if (timeKey(task.due_at) >= '10:00') {
      push(relative('due_day:0', 'Утром в день срока', 'due_day', 0, task))
    }
  } else if (task.due_at) {
    push(relative('due_day:0', 'В день срока', 'due_day', 0, task))
    push(relative('due_day:1440', 'Накануне', 'due_day', 1440, task))
  }
  if (task.start_at) {
    push(
      task.start_has_time
        ? relative('start:0', 'К началу', 'start', 0, task)
        : relative('start_day:0', 'В день начала', 'start_day', 0, task),
    )
  }
  const inHour = minuteIso(now + 60 * MINUTE)
  out.push({
    key: 'at:hour',
    label: 'Через 1 час',
    group: 'time',
    body: { anchor: 'at', fire_at: inHour },
    fireAt: inHour,
  })
  const tomorrow = dayTimeToIso(addDaysKey(dayKey(now), 1), REMINDER_DAY_HOUR)
  if (tomorrow) {
    out.push({
      key: 'at:tomorrow',
      label: 'Завтра утром',
      group: 'time',
      body: { anchor: 'at', fire_at: tomorrow },
      fireAt: tomorrow,
    })
  }

  const taken = new Set(
    existing.map((r) =>
      r.anchor === 'at' && r.fire_at ? `at@${minuteIso(Date.parse(r.fire_at))}` : `${r.anchor}:${r.offset_minutes}`,
    ),
  )
  const seenMoments = new Set<string>()
  const result: ReminderPreset[] = []
  for (const p of out) {
    const moment = minuteIso(Date.parse(p.fireAt))
    if (Date.parse(p.fireAt) <= now + MINUTE) continue
    const takenKey = p.body.anchor === 'at' ? `at@${moment}` : p.key
    if (taken.has(takenKey) || seenMoments.has(moment)) continue
    seenMoments.add(moment)
    result.push({ ...p, hint: momentHint(p.fireAt, now) })
  }
  return result
}

/**
 * Почему новое напоминание поставить нельзя; null — можно. Зеркало 409 ручки
 * POST: выполненная задача и потолок на задачу.
 *
 * Причину обязательно называть словами: без неё шторка на телефоне у закрытой
 * задачи открывалась пустой — заголовок и «Готово», ни вариантов, ни
 * объяснения (ОС владельца 24.09, iPhone).
 */
export type ReminderAddBlock = 'done' | 'limit'

export function reminderAddBlock(
  task: Pick<Task, 'done'>,
  items: readonly TaskReminderItem[],
): ReminderAddBlock | null {
  if (task.done) return 'done'
  return items.length >= MAX_REMINDERS_PER_TASK ? 'limit' : null
}

/** Коротко — в строку свойств и рядом с чипами. */
export function reminderBlockLabel(block: ReminderAddBlock): string {
  return block === 'done' ? 'Задача выполнена' : `Не больше ${MAX_REMINDERS_PER_TASK} на задачу`
}

/** Полностью — пояснение в шторке. */
export function reminderBlockText(block: ReminderAddBlock): string {
  return block === 'done'
    ? 'Задача выполнена — напоминания по ней не приходят. Поставить новое можно, когда задачу вернут в работу.'
    : `На задачу — не больше ${MAX_REMINDERS_PER_TASK} напоминаний. Удалите одно, чтобы поставить другое.`
}

/** Название напоминания: «За 1 ч до срока», «Накануне, 9:00», «30.09 в 16:42». */
export function reminderLabel(item: TaskReminderItem, now: number): string {
  const off = item.offset_minutes
  switch (item.anchor) {
    case 'at':
      return item.fire_at ? momentText(item.fire_at, now) : 'Своё время'
    case 'due':
      if (off === 0) return 'К сроку'
      if (off === 1440) return 'За 1 день до срока'
      if (off % 60 === 0) return `За ${off / 60} ч до срока`
      return `За ${off} мин до срока`
    case 'due_day':
      return off === 0 ? 'Утром в день срока' : off === 1440 ? 'Накануне, 9:00' : 'До дня срока'
    case 'start':
      return off === 0 ? 'К началу' : `За ${off} мин до начала`
    case 'start_day':
      return 'В день начала, 9:00'
  }
}

/** Вторая строка: когда придёт, когда пришло или почему не сработает. */
export function reminderStatus(item: TaskReminderItem, now: number): string {
  const aboutStart = item.anchor === 'start' || item.anchor === 'start_day'
  switch (item.state) {
    case 'armed':
      return item.fire_at ? momentText(item.fire_at, now) : ''
    case 'fired':
      return item.fired_at ? `пришло ${momentText(item.fired_at, now)}` : 'пришло'
    case 'no_date':
      return aboutStart ? 'Не сработает — у задачи нет даты начала' : 'Не сработает — у задачи нет срока'
    case 'passed':
      return aboutStart ? 'Не сработает — время начала прошло' : 'Не сработает — время срока прошло'
    case 'done':
      return 'Не сработает — задача выполнена'
    case 'archived':
      return 'Не сработает — задача в архиве'
  }
}

/** Честная подсказка: куда реально придёт напоминание. null — всё хорошо. */
export function deliveryHint(d: ReminderDelivery | undefined): string | null {
  if (!d) return null
  if (!d.push_on && !d.inapp_on) return 'Напоминания выключены в настройках уведомлений.'
  if (!d.push_on) return 'Пуш-напоминания выключены в настройках — придёт только во «Входящие».'
  if (d.push_devices === 0) {
    return 'Напоминание придёт только во «Входящие»: пуш-уведомления не включены ни на одном вашем устройстве.'
  }
  return null
}

/** Пометка «время московское» — только если часы устройства показывают другое. */
export function timezoneNote(now: number, localHM: (ms: number) => string = localTimeKey): string | null {
  return localHM(now) === timeKey(now) ? null : 'Время — московское'
}

function localTimeKey(ms: number): string {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/**
 * Тост в открытом приложении: счётчик непрочитанных вырос, и новейшее
 * непрочитанное — свежее напоминание. Без тоста у сотрудника без пуш-подписки
 * (таких большинство) напоминание было бы только тихим бейджем.
 */
export function shouldToastReminder(
  prevCount: number | undefined,
  nextCount: number,
  latest: { kind: string; is_read: boolean; created_at: string } | undefined,
  now: number,
): boolean {
  if (prevCount === undefined || nextCount <= prevCount || !latest) return false
  if (latest.kind !== 'task.reminder' || latest.is_read) return false
  return now - Date.parse(latest.created_at) < 2 * MINUTE
}
