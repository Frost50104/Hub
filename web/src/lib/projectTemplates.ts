/**
 * Шаблоны проектов (0060): API и чистые правила экранов.
 *
 * Шаблон — обычный проект с `is_template`, невидимый всему коду, пока его не
 * открыл сервер; страница шаблона — та же `ProjectPage`. Здесь всё, что клиент
 * решает про шаблон сам: видимость входов, подписи строк, строки предпросмотра
 * и правила страницы. Права (`can_edit`) считает СЕРВЕР — клиент их не выводит.
 */

import { formatBytes } from '@/lib/attachmentTypes'
import { type Project } from '@/lib/projects'
import { dueDayToIso, shortDate } from '@/lib/taskDates'
import { plural } from '@/lib/typography'
import type { Me } from '@/hooks/useMe'

export interface TemplateListItem {
  id: string
  key: string
  name: string
  description: string | null
  badge_emoji: string | null
  badge_url: string | null
  template_anchor_on: string | null
  created_by: string
  author_name: string | null
  author_deleted: boolean
  task_count: number
  attachment_count: number
  attachment_bytes: number
  member_count: number
  use_count: number
  can_edit: boolean
  updated_at: string
}

export interface DroppedPerson {
  employee_id: string
  name: string
  tasks: number
}

export interface CopyPreview {
  tasks: number
  subtasks: number
  too_big: boolean
  max_tasks: number
  dropped: { archived: number; orphan_subtasks: number; recurrence_steps: number }
  dropped_people: DroppedPerson[]
  attachments: number
  attachment_bytes: number
  members: number
  notify_people: number
  first_due: string | null
  last_due: string | null
  overdue_after_shift: number
  due_soon_reminders: number
  suggested_anchor_on: string
  shift_days: number
  start_on: string | null
  disk_ok: boolean
}

export interface CopyReport {
  tasks: number
  subtasks: number
  dropped: CopyPreview['dropped']
  dropped_people: DroppedPerson[]
  attachments_copied: number
  attachments_missing: number
  notified: number
}

export interface TemplateCreateBody {
  name: string
  description?: string
  anchor_on?: string
}

export interface SaveAsTemplateBody {
  name: string
  anchor_on?: string
  include_members: boolean
  include_attachments: boolean
}

export interface ProjectFromTemplateBody {
  name: string
  start_on?: string
  folder_id?: string | null
  include_members: boolean
  include_attachments: boolean
}

export interface TemplateSettings {
  enabled: boolean
  env_enabled: boolean
}


// ─── Входы ───────────────────────────────────────────────────────────────────

/** Модуль включён для тенанта (старый бэкенд поля не шлёт — выключен). */
export function templatesEnabled(me: Me | undefined): boolean {
  return me?.features?.project_templates === true
}

/**
 * Пункт «Шаблоны» и режим «По шаблону»: модуль включён и человек может
 * создавать проекты. hub-admin видит пункт ВСЕГДА при включённом env-флаге —
 * тумблер модуля живёт на экране библиотеки, и иначе включить его было бы
 * неоткуда (тот же приём, что у сегмента гонки).
 */
export function templatesNavVisible(me: Me | undefined): boolean {
  if (me?.features?.project_templates_admin === true) return true
  return templatesEnabled(me) && me?.can_create_projects === true
}

/** Режим «По шаблону» в диалоге «Новый проект» — только при включённом модуле. */
export function templateModeAvailable(me: Me | undefined): boolean {
  return templatesEnabled(me) && me?.can_create_projects === true
}

// ─── Даты ────────────────────────────────────────────────────────────────────

/** «1 сентября 2026» из ключа дня `YYYY-MM-DD`. */
export function longDay(key: string): string {
  const d = new Date(`${key}T12:00:00Z`)
  if (Number.isNaN(d.getTime())) return key
  return d
    .toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
    .replace(/\s*г\.$/, '')
}

function shortDay(key: string): string {
  return shortDate(dueDayToIso(key))
}

// ─── Библиотека ──────────────────────────────────────────────────────────────

/** «42 задачи · 5 вложений · автор Иванова А. · использован 3 раза». */
export function templateRowMeta(item: TemplateListItem): string {
  const parts = [plural(item.task_count, 'задача', 'задачи', 'задач')]
  if (item.attachment_count > 0) {
    parts.push(plural(item.attachment_count, 'вложение', 'вложения', 'вложений'))
  }
  if (item.author_deleted) {
    parts.push('автор уволен — правит администратор')
  } else if (item.author_name) {
    parts.push(`автор ${item.author_name}`)
  }
  parts.push(
    item.use_count === 0
      ? 'ещё не использован'
      : `использован ${plural(item.use_count, 'раз', 'раза', 'раз')}`,
  )
  return parts.join(' · ')
}

/** Поле фильтра над списком — когда шаблонов больше десяти (порог дизайн-системы). */
export const TEMPLATE_FILTER_FROM = 11

// ─── Предпросмотр ────────────────────────────────────────────────────────────

/** Строки блока «Будет создано». */
export function previewFacts(p: CopyPreview): string[] {
  const tasks = plural(p.tasks, 'задача', 'задачи', 'задач')
  const out = [p.subtasks > 0 ? `${tasks} и ${plural(p.subtasks, 'подзадача', 'подзадачи', 'подзадач')}` : tasks]
  if (p.attachments > 0) {
    out.push(
      `${plural(p.attachments, 'вложение', 'вложения', 'вложений')} · ${formatBytes(p.attachment_bytes)}`,
    )
  }
  if (p.members > 0) out.push(plural(p.members, 'участник', 'участника', 'участников'))
  if (p.first_due && p.last_due) {
    out.push(
      p.first_due === p.last_due
        ? `Срок ${shortDay(p.first_due)}`
        : `Сроки ${shortDay(p.first_due)} — ${shortDay(p.last_due)}`,
    )
  }
  return out
}

/** «Уведомим 5 человек — каждому одно сообщение…»; null — уведомлять некого. */
export function previewNotifyLine(p: CopyPreview): string | null {
  if (p.notify_people === 0) return null
  return `Уведомим ${plural(p.notify_people, 'человека', 'человек', 'человек')} — каждому одно сообщение с числом его задач.`
}

export interface PreviewWarning {
  /** Что за предупреждение — по нему фильтруют, а не по тексту или цвету:
   *  «Сохранить как шаблон» про просрочку и напоминания молчит — шаблон
   *  уведомлений не шлёт, сроки сдвинутся при создании проекта. */
  kind: 'too_big' | 'disk' | 'overdue' | 'dropped' | 'due_soon'
  tone: 'red' | 'amber' | 'blue'
  text: string
}

/**
 * Предупреждения до нажатия — в порядке важности. `includeAttachments=false`
 * снимает «мало места»: без вложений копировать на диск нечего.
 */
export function previewWarnings(
  p: CopyPreview,
  { includeAttachments = true }: { includeAttachments?: boolean } = {},
): PreviewWarning[] {
  const out: PreviewWarning[] = []
  if (p.too_big) {
    out.push({
      kind: 'too_big',
      tone: 'red',
      text: `Задач больше ${p.max_tasks} — такой объём за раз не копируется.`,
    })
  }
  if (!p.disk_ok && includeAttachments) {
    out.push({
      kind: 'disk',
      tone: 'red',
      text: 'На сервере мало места для копий вложений — снимите галочку «Вложения».',
    })
  }
  if (p.overdue_after_shift > 0) {
    out.push({
      kind: 'overdue',
      tone: 'red',
      text: `${plural(p.overdue_after_shift, 'задача сразу будет просрочена', 'задачи сразу будут просрочены', 'задач сразу будут просрочены')}: исполнители начнут получать напоминание каждый день.`,
    })
  }
  for (const person of p.dropped_people) {
    out.push({
      kind: 'dropped',
      tone: 'amber',
      text:
        person.tasks > 0
          ? `Не перенесётся: ${person.name || 'уволенный сотрудник'} — ${plural(person.tasks, 'задача останется', 'задачи останутся', 'задач останутся')} без исполнителя.`
          : `Не перенесётся в участники: ${person.name || 'уволенный сотрудник'}.`,
    })
  }
  if (p.due_soon_reminders > 0) {
    out.push({
      kind: 'due_soon',
      tone: 'blue',
      text: `В ближайшие сутки придёт ${plural(p.due_soon_reminders, 'напоминание', 'напоминания', 'напоминаний')} о сроке.`,
    })
  }
  return out
}

/** Что НЕ попадёт в шаблон при сохранении проекта; null — всё попадёт. */
export function droppedSummary(d: CopyPreview['dropped']): string | null {
  const parts: string[] = []
  if (d.archived > 0) parts.push(plural(d.archived, 'архивная', 'архивные', 'архивных'))
  if (d.orphan_subtasks > 0) {
    parts.push(plural(d.orphan_subtasks, 'подзадача архивной задачи', 'подзадачи архивных задач', 'подзадач архивных задач'))
  }
  if (d.recurrence_steps > 0) {
    parts.push(plural(d.recurrence_steps, 'выполненный шаг повтора', 'выполненных шага повтора', 'выполненных шагов повтора'))
  }
  return parts.length ? `Не попадут: ${parts.join(', ')}.` : null
}

/** Тост после создания проекта по шаблону. */
export function reportDescription(r: CopyReport): string {
  const total = r.tasks + r.subtasks
  const parts = [plural(total, 'задача', 'задачи', 'задач')]
  if (r.dropped_people.length > 0) {
    parts.push(`не перенесены: ${r.dropped_people.map((d) => d.name || 'уволенный сотрудник').join(', ')}`)
  }
  if (r.attachments_missing > 0) {
    parts.push(`не найдено файлов: ${r.attachments_missing}`)
  }
  if (r.notified > 0) {
    parts.push(`уведомлено ${plural(r.notified, 'человек', 'человека', 'человек')}`)
  }
  // Разделитель « · », как у сводок строк: через точки выходило «Петров А..»
  // и предложения с маленькой буквы.
  return parts.join(' · ')
}

// ─── Страница шаблона ────────────────────────────────────────────────────────

export interface TemplatePageGate {
  isTemplate: boolean
  /** «Поделиться», звезда, «Дашборд», пресеты фильтра по датам. */
  showShare: boolean
  showFavorite: boolean
  showDashboard: boolean
  showDatePresets: boolean
  /** «Изменить точку отсчёта» — автор и hub-admin (сервер: can_edit). */
  canEditAnchor: boolean
}

/**
 * Что прячет страница проекта, когда это шаблон. Одна чистая функция по
 * образцу `projectAboutGate`: иначе правила расползлись бы по JSX.
 */
export function templatePageGate(
  project: Pick<Project, 'is_template' | 'can_edit'> | undefined,
): TemplatePageGate {
  const isTemplate = project?.is_template === true
  return {
    isTemplate,
    showShare: !isTemplate,
    showFavorite: !isTemplate,
    showDashboard: !isTemplate,
    showDatePresets: !isTemplate,
    canEditAnchor: isTemplate && project?.can_edit === true,
  }
}

// ─── Форма «Новый проект → По шаблону» ───────────────────────────────────────

export interface FromTemplateDraft {
  name: string
  templateId: string | null
  includeAttachments: boolean
}

/**
 * Можно ли жать «Создать проект». Зеркало серверных отказов, чтобы кнопка не
 * обещала то, что сервер отклонит: потолок задач (409) и место на диске (507,
 * только если вложения копируются). Старт в прошлом разрешён (решение
 * владельца 21.09) — о цене говорит предупреждение, а не блокировка.
 */
export function fromTemplateReady(draft: FromTemplateDraft, preview: CopyPreview | undefined): boolean {
  if (!draft.name.trim() || !draft.templateId || !preview) return false
  if (preview.too_big) return false
  if (!preview.disk_ok && draft.includeAttachments) return false
  return true
}
