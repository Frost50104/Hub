/**
 * Экран «О проекте»: черновик формы, тело PATCH, подтверждение удаления.
 *
 * Чистый модуль — vitest без jsdom. Здесь живут решения, которые дороже всего
 * потерять: пустой PATCH не уходит, очистка описания шлёт `''`, а не `null`.
 */

import { NBSP, plural } from '@/lib/typography'

export interface ProjectProfileDraft {
  name: string
  description: string
}

export interface ProjectProfileSource {
  name: string
  description: string | null
}

export function projectProfileDraft(project: ProjectProfileSource): ProjectProfileDraft {
  return { name: project.name, description: project.description ?? '' }
}

export function projectProfileDirty(
  draft: ProjectProfileDraft,
  project: ProjectProfileSource,
): boolean {
  return projectProfilePatch(draft, project) !== null
}

/**
 * Тело PATCH или null, если менять нечего.
 *
 * ГЛАВНОЕ: очистка описания уходит пустой строкой. Сервер игнорирует `None`
 * (идиома `if body.description is not None`), поэтому `null` означал бы «не
 * менять» — и описание нельзя было бы стереть НИКОГДА.
 *
 * Имя триммится, описание — нет: хвостовой перенос строки в тексте документа
 * пользователь поставил намеренно.
 */
export function projectProfilePatch(
  draft: ProjectProfileDraft,
  project: ProjectProfileSource,
): { name?: string; description?: string } | null {
  const patch: { name?: string; description?: string } = {}
  const name = draft.name.trim()
  if (name && name !== project.name) patch.name = name
  if (draft.description !== (project.description ?? '')) {
    patch.description = draft.description
  }
  return Object.keys(patch).length > 0 ? patch : null
}

export function projectNameError(name: string): string | null {
  const trimmed = name.trim()
  if (!trimmed) return 'Название не может быть пустым'
  if (trimmed.length > 255) return 'Название длиннее 255 символов'
  return null
}

/**
 * Первая осмысленная строка описания без разметки — для шапки проекта и
 * подписи в списке.
 *
 * Нужна не ради красоты: описание выросло до 20 000 символов, а шапка кладёт
 * его целиком в `title` (тултип на две страницы), список же склеивает по
 * описанию каждого из полусотни проектов.
 */
export function summarizeProjectDescription(
  markdown: string | null | undefined,
  limit = 160,
): string | null {
  if (!markdown) return null
  const flat = markdown
    .replace(/```[\s\S]*?```/g, ' ') // блоки кода целиком
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ') // картинки
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1') // ссылки → текст
    .replace(/^\s{0,3}#{1,6}\s+/gm, '') // заголовки
    .replace(/^\s{0,3}[-*+]\s+/gm, '') // маркеры списка
    .replace(/^\s{0,3}>\s?/gm, '') // цитаты
    .replace(/[*_`~]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!flat) return null
  return flat.length > limit ? `${flat.slice(0, limit).trimEnd()}…` : flat
}

/**
 * Ключ введён верно? Регистр и пробелы не важны: заставлять жать Caps Lock
 * ради «PLP» — враждебность, а не защита. Защита здесь от промаха.
 */
export function confirmKeyMatches(input: string, key: string): boolean {
  return input.trim().toLowerCase() === key.trim().toLowerCase()
}

export interface BlastRadius {
  tasks: number
  attachments: number
}

/** «Будут удалены 214 задач и 12 вложений». Нули опускаем. */
export function describeProjectBlastRadius(counts: BlastRadius): string {
  const parts: string[] = []
  if (counts.tasks > 0) parts.push(plural(counts.tasks, 'задача', 'задачи', 'задач'))
  if (counts.attachments > 0) {
    parts.push(plural(counts.attachments, 'вложение', 'вложения', 'вложений'))
  }
  // У пустого проекта оговорка про комментарии и историю была бы враньём —
  // поэтому она внутри, а не приклеена снаружи вызывающим.
  if (parts.length === 0) return 'Проект пуст — удалять нечего, кроме него самого.'
  return (
    `Будут удалены ${parts.join(' и ')}, а вместе с задачами — ` +
    'их комментарии и история. Восстановить это будет нельзя.'
  )
}

/**
 * Незакоммиченные черновики «О проекте», по одному на проект.
 *
 * Вкладка размонтируется при переключении вида, а сохранение здесь — явной
 * кнопкой (в отличие от карточки задачи, где коммитит blur). Без этой памяти
 * человек, ушедший на «Список» и вернувшийся, терял бы набранное молча — а
 * набрано может быть до 20 000 знаков.
 *
 * Модульная Map, а не стор: живёт до перезагрузки страницы, между вкладками
 * браузера не шарится и ничего не персистит. Черновик снимается при
 * сохранении и при явной отмене.
 */
const drafts = new Map<string, ProjectProfileDraft>()

export function rememberProjectDraft(id: string, draft: ProjectProfileDraft): void {
  drafts.set(id, draft)
}

export function forgetProjectDraft(id: string): void {
  drafts.delete(id)
}

/** Запомненный черновик или свежий из проекта. */
export function restoreProjectDraft(
  id: string,
  project: ProjectProfileSource,
): ProjectProfileDraft {
  return drafts.get(id) ?? projectProfileDraft(project)
}

/* ── Кто что видит на экране «О проекте» ─────────────────────────────────── */

/** Ровно те поля, от которых зависят права. Не весь `Project`: чистый модуль
 *  не должен зависеть от формы ответа API. */
export interface ProjectAboutSource {
  can_edit: boolean
  can_manage: boolean
  archived_at: string | null
  is_personal?: boolean
  /** Шаблон проекта (0060): архива у него нет, «сохранить как шаблон» — тоже. */
  is_template?: boolean
}

export interface ProjectAboutGate {
  /** Имя, описание, бейдж. Сервер: PATCH /projects/{id} и обе ручки бейджа
   *  стоят на EDIT_ROLES — то есть ровно на том, что обещает `can_edit`. */
  canEditProfile: boolean
  /** Импорт CSV — тоже edit-tier. Архив сервер НЕ сторожит (ни PATCH, ни
   *  импорт не смотрят `archived_at`) — прятать импорт в архиве это решение
   *  фронта, и оно живёт здесь, а не в JSX, где «упрощение» его потеряет. */
  canImport: boolean
  /** Архив и разархив — только владелец, и не у личного проекта (409). */
  canArchive: boolean
  /** Удаление — те же условия. */
  canDelete: boolean
  /** «Сохранить как шаблон» (0060): модуль включён, человек создаёт проекты и
   *  владеет этим; не личный (сервер 409 даже hub-admin'у) и не сам шаблон. */
  canSaveAsTemplate: boolean
  /** Показывать ли кнопку «Настройки проекта». */
  canOpenSettings: boolean
  /** Строка внизу настроек, объясняющая, чего в них нет. null — объяснять нечего. */
  settingsLimitNote: string | null
}

export function projectAboutGate(
  project: ProjectAboutSource,
  { templatesOn = false, canCreateProjects = false }: { templatesOn?: boolean; canCreateProjects?: boolean } = {},
): ProjectAboutGate {
  const archived = project.archived_at !== null
  const personal = project.is_personal === true
  const template = project.is_template === true

  const canEditProfile = project.can_edit
  const canImport = project.can_edit && !archived
  // Шаблон не архивируется: прятать нечего — его и так не видит никто, кроме
  // библиотеки. Сервер на архив шаблона отвечает 404.
  const canArchive = project.can_manage && !personal && !template
  const canDelete = project.can_manage && !personal
  const canSaveAsTemplate =
    templatesOn && canCreateProjects && project.can_manage && !personal && !template

  // Именно ИЛИ, а не `= canEditProfile`. Равенство держится только потому, что
  // на сервере MANAGE_ROLES ⊆ EDIT_ROLES. Если ступени однажды разъедутся,
  // экран деградирует в «настройки открылись и в них ровно то, что можно», а
  // не в «кнопка пропала у управляющего».
  const canOpenSettings =
    canEditProfile || canImport || canArchive || canDelete || canSaveAsTemplate

  let settingsLimitNote: string | null = null
  if (canOpenSettings && personal) {
    // Владельцу личного пространства сказать «может только владелец» было бы
    // враньём: он и есть владелец.
    settingsLimitNote =
      'Личное пространство: его нельзя архивировать и удалить, а открывается оно на «Моих задачах».'
  } else if (canOpenSettings && !project.can_manage && !template) {
    settingsLimitNote = 'Архивировать и удалить проект может только владелец.'
  }

  return {
    canEditProfile,
    canImport,
    canArchive,
    canDelete,
    canSaveAsTemplate,
    canOpenSettings,
    settingsLimitNote,
  }
}

/* ── Сводка в режиме чтения ──────────────────────────────────────────────── */

export interface ProjectSummaryInput {
  key: string
  /** Уже отформатированная дата: `toLocaleDateString` под vitest зависит от
   *  сборки ICU в Node, а локаль-флейк хуже отсутствия теста. */
  createdLabel: string
  task_count?: number | null
  done_count?: number | null
  /** null — список участников ещё не пришёл: ряд остаётся, значение скелетон. */
  memberCount: number | null
  ownerNames: string[]
}

export type ProjectSummaryRow =
  | { kind: 'key'; label: string; value: string }
  | { kind: 'text'; label: string; value: string }
  | { kind: 'pending'; label: string }

/**
 * Ряды сводки. Кодирует правило «`undefined` ≠ `0`»: счётчиков может не быть
 * вовсе (их заполняют не все ручки), и тогда ряда нет — а не «—» и не «0».
 */
export function projectSummaryRows(input: ProjectSummaryInput): ProjectSummaryRow[] {
  const rows: ProjectSummaryRow[] = [
    { kind: 'key', label: 'Ключ', value: input.key },
  ]

  const total = input.task_count
  if (total != null) {
    rows.push({
      kind: 'text',
      label: 'Задач',
      value: total === 0 ? 'Пока нет задач' : plural(total, 'задача', 'задачи', 'задач'),
    })
    // «0 из 0» — шум: предыдущий ряд уже сказал, что задач нет.
    if (total > 0 && input.done_count != null) {
      rows.push({ kind: 'text', label: 'Выполнено', value: `${input.done_count} из ${total}` })
    }
  }

  rows.push({ kind: 'text', label: 'Создан', value: input.createdLabel })

  rows.push(
    input.memberCount === null
      ? { kind: 'pending', label: 'Участников' }
      : {
          kind: 'text',
          label: 'Участников',
          value: plural(input.memberCount, 'участник', 'участника', 'участников'),
        },
  )

  const [first, ...rest] = input.ownerNames
  if (first) {
    rows.push({
      kind: 'text',
      label: 'Владелец',
      value: rest.length > 0 ? `${first} и ещё ${rest.length}` : first,
    })
  }

  return rows
}

/**
 * Подпись строки проекта в списках: «312 задач · 48 закрыто · суть описания».
 *
 * Живёт здесь, а не в странице списка: с появлением экрана архива у неё стало
 * два потребителя, а копипаста двух форматов разъехалась бы на первой же
 * правке. `task_count === undefined` («сервер не считал») и `0` («задач нет»)
 * — РАЗНЫЕ вещи: в первом случае части нет вовсе.
 */
export function projectContext(project: {
  task_count?: number | null
  done_count?: number | null
  description: string | null
}): string {
  const parts: string[] = []
  if (project.task_count != null) {
    if (project.task_count === 0) parts.push('Пока нет задач')
    else {
      parts.push(plural(project.task_count, 'задача', 'задачи', 'задач'))
      if ((project.done_count ?? 0) > 0) parts.push(`${project.done_count}${NBSP}закрыто`)
    }
  }
  // Сводка, а не полное описание: полсотни проектов × 20 000 знаков — это
  // мегабайт текстовых узлов, которые потом обрежет CSS.
  const summary = summarizeProjectDescription(project.description, 80)
  if (summary) parts.push(summary)
  return parts.join(' · ')
}
