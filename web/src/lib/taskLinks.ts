/**
 * Куда ведёт клик по задаче и где живёт её карточка.
 *
 * Обобщение `createdTaskLocation`: с 16.09 личная задача открывается не на
 * странице скрытого проекта (её больше нет — `/projects/{мой личный}`
 * редиректит на `/my`), а на самих «Моих задачах». Правило одно на четыре
 * места, которые раньше решали это каждое по-своему: строка списка, карточка
 * после переноса задачи в личное, панель «Главной» и диалог создания.
 */

export interface TaskLocationInput {
  taskId: string
  projectId: string
  /** `me.personal_project_id`. */
  personalProjectId: string | null | undefined
  /** `location.pathname` — чтобы сохранить фильтры, оставаясь на месте. */
  pathname?: string
  /** `location.search`, с ведущим «?» или пустая строка. */
  search?: string
}

/**
 * `search` МЕРЖИТСЯ, когда pathname совпадает с текущим: открыть карточку
 * прямо на доске с фильтрами (`?view=board&f_priority=high`) не должно
 * выкидывать человека в список и снимать фильтры.
 */
export function taskLocation(input: TaskLocationInput): {
  pathname: string
  search: string
} {
  const personal =
    !!input.personalProjectId && input.projectId === input.personalProjectId
  const pathname = personal ? '/my' : `/projects/${input.projectId}`
  // Параметры чужой страницы не тащим: фильтры проекта X в проекте Y — мусор.
  const params = new URLSearchParams(
    pathname === input.pathname ? (input.search ?? '') : '',
  )
  if (personal) params.set('tab', 'personal')
  params.set('task', input.taskId)
  return { pathname, search: `?${params.toString()}` }
}
