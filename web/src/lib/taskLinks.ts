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

export interface ProjectLocationInput {
  projectId: string
  /** `me.personal_project_id`. */
  personalProjectId: string | null | undefined
  /** `location.pathname` — сохранить фильтры, оставаясь на той же странице. */
  pathname?: string
  /** `location.search`, с ведущим «?» или пустая строка. */
  search?: string
}

/**
 * Адрес СТРАНИЦЫ проекта — без `?task=`.
 *
 * Пара к `taskLocation`: «открыть проект» из чипа в строке задачи или из
 * строки «Проект» карточки (16.09). Своё личное — это вкладка «Личные» на
 * «Моих задачах»: страницы у личного проекта нет. Search сохраняется только
 * на той же странице (клик по имени проекта на его же доске не должен снимать
 * `?view=board&f_*`), а `task` снимается всегда: «открыть проект» — увидеть
 * проект, а не проект с той же карточкой поверх.
 */
export function projectLocation(input: ProjectLocationInput): string {
  const personal =
    !!input.personalProjectId && input.projectId === input.personalProjectId
  const pathname = personal ? '/my' : `/projects/${input.projectId}`
  const params = new URLSearchParams(
    pathname === input.pathname ? (input.search ?? '') : '',
  )
  params.delete('task')
  if (personal) params.set('tab', 'personal')
  const query = params.toString()
  return query ? `${pathname}?${query}` : pathname
}

/**
 * Текущий адрес без `?task=`. Нужен карточке: если «открыть проект» ведёт на
 * ту же страницу, где она открыта, достаточно закрыть карточку — второй
 * переход на тот же адрес лишь положил бы дубль в историю.
 */
export function locationWithoutTask(pathname: string, search: string): string {
  const params = new URLSearchParams(search)
  params.delete('task')
  const query = params.toString()
  return query ? `${pathname}?${query}` : pathname
}
