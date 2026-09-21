import type { Project } from './projects'

/**
 * Куда «Новая задача» вправе положить задачу.
 *
 * Отдельным модулем, потому что сломалась именно эта логика, а vitest в проекте
 * бежит без jsdom — компонент покрыть нечем. Прецедент — `lib/personalTasks.ts`.
 */
export interface CreateTaskTarget {
  value: string
  label: string
}

/** Значение прочерка. Пустая строка, а не `null` — это `value` у `<option>`. */
export const PERSONAL_TARGET = ''

/**
 * «Личные задачи сотрудника» — поручение (15.09).
 *
 * Отдельное значение, а не id проекта: чужой личный проект клиенту неизвестен
 * и знать его он не должен (`GET /projects` личные не отдаёт никому). Адресуем
 * человеком, проект резолвит сервер — `POST /api/me/delegate`.
 */
export const DELEGATE_TARGET = 'delegate'

/**
 * Проекты, куда человек реально может писать.
 *
 * Фильтр по `can_edit` обязателен: `GET /projects` отдаёт и те, где ты
 * наблюдатель, а `POST /projects/{id}/tasks` требует owner/editor и ответит
 * 403. Предлагать такое в диалоге — и был исходный баг: у сотрудника с одним
 * viewer-проектом кнопка «Новая задача» вела в тупик.
 *
 * Личного проекта здесь нет и быть не может: `GET /projects` не отдаёт его
 * никогда (серверный инвариант `personal_projects.py`). Он приходит прочерком.
 */
export function createTaskTargets(
  projects: Project[] | undefined,
  current?: Project,
): CreateTaskTarget[] {
  const out = (projects ?? [])
    .filter((p) => p.can_edit)
    .map((p) => ({ value: p.id, label: p.name }))
  // Проект, со страницы которого открыли диалог, — даже если его нет в
  // `GET /projects`. Так живёт шаблон (0060): списки его не видят по
  // построению, и без этой строки `initialTarget` уронил бы задачу в личное
  // пространство автора (у FAB, сайдбара и шапки проекта — только id).
  if (current && current.can_edit && !out.some((t) => t.value === current.id)) {
    out.unshift({
      value: current.id,
      label: current.is_template ? `${current.name} (шаблон)` : current.name,
    })
  }
  return out
}

/**
 * Что выбрано при открытии.
 *
 * По умолчанию — прочерк, то есть личные задачи. Исключение одно: диалог
 * открыли со страницы проекта, и этот проект доступен — тогда прочерк был бы
 * издевательством, человек нажал «Задача» внутри проекта.
 */
export function initialTarget(
  targets: CreateTaskTarget[],
  initialProjectId: string | undefined,
): string {
  if (initialProjectId && targets.some((t) => t.value === initialProjectId)) {
    return initialProjectId
  }
  return PERSONAL_TARGET
}

/**
 * Куда пойдёт запрос. `null` — писать некуда: ни личного проекта, ни прав.
 * Тогда форма обязана быть неотправляемой, а не молча падать на 404.
 */
export function resolveProjectId(
  target: string,
  personalProjectId: string | null | undefined,
): string | null {
  // Поручение проектом не адресуется — его резолвит сервер по человеку.
  if (target === DELEGATE_TARGET) return null
  if (target !== PERSONAL_TARGET) return target
  return personalProjectId ?? null
}

/**
 * Можно ли отправлять форму.
 *
 * Три ветки вместо одной `projectId !== null`: у поручения проекта нет вовсе,
 * зато обязателен выбранный человек — без него форма молча улетала бы в 422.
 */
export function createTaskReady(input: {
  target: string
  title: string
  projectId: string | null
  delegateTo: string | null
}): boolean {
  if (!input.title.trim()) return false
  if (input.target === DELEGATE_TARGET) return input.delegateTo !== null
  return input.projectId !== null
}

/**
 * Адрес карточки только что созданной задачи.
 *
 * Две ветки, потому что личного проекта «не существует»: его нет ни в одном
 * списке проектов, и карточка личной задачи живёт на `/my`, а не на странице
 * скрытого проекта. Рабочая задача открывается там, где живёт, — в проекте.
 *
 * `search` МЕРЖИТСЯ, когда pathname совпадает с текущим. Без этого создание
 * задачи прямо на доске с фильтрами (`?view=board&f_priority=high`) выкинуло бы
 * человека в список и сняло фильтры: у страницы проекта вкладка и фильтры живут
 * в тех же query-параметрах, и `openTask` там как раз мержит.
 */
export function createdTaskLocation(input: {
  taskId: string
  projectId: string
  isPersonal: boolean
  /** `location.pathname` на момент отправки формы. */
  pathname: string
  /** `location.search`, с ведущим «?» или пустая строка. */
  search: string
}): { pathname: string; search: string } {
  const pathname = input.isPersonal ? '/my' : `/projects/${input.projectId}`
  // Параметры чужой страницы не тащим: фильтры проекта X в проекте Y — мусор.
  const params = new URLSearchParams(pathname === input.pathname ? input.search : '')
  params.set('task', input.taskId)
  return { pathname, search: `?${params.toString()}` }
}
