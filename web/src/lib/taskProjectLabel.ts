/**
 * Чем подписать строку кросс-проектного списка в колонке «Проект».
 *
 * Три случая, и каждый раньше решался неверно:
 *
 * 1. **Моя личная задача.** Живое имя проекта с 16.09 — «Мои задачи», и на
 *    экране с тем же заголовком колонка «Проект» говорила бы «Мои задачи».
 *    Пишем «Личное».
 * 2. **Чужое личное** (задача, поручённая мне, или моё поручение коллеге).
 *    Этого проекта нет в `GET /projects` ни у кого, и код падал на фолбэк
 *    `project_key` — то есть печатал `LICNOE26`, а после перевыдачи ключей
 *    начал бы печатать фамилию владельца. Пишем нейтральное «Личное коллеги».
 * 3. **Обычный проект.** Имя из `useProjects()`, а если его там нет —
 *    `project_key`: так выглядит проект, из которого человека убрали, но
 *    задача на нём осталась (на проде таких 19).
 *
 * Различить (2) и (3) на клиенте нечем — «нет в списке проектов» верно для
 * обоих. Поэтому опираемся на серверный `project_is_personal`; для вчерашних
 * бандлов и ручек, которые его не заполняют, поле `null` и ветка (2)
 * не срабатывает вовсе.
 */

import { projectLocation } from './taskLinks'
import { type Task } from './tasks'

/**
 * `to` — куда ведёт клик по чипу (16.09): своё личное — на вкладку «Личные»
 * (`/my?tab=personal`, страницы у личного проекта нет), обычный проект и чужое
 * личное — на страницу проекта (участник по построению: чужое личное видно
 * только исполнителю и наблюдателю, а им `ensure_project_member` выдал
 * viewer). Фолбэк ключа — `null`: имени нет в `GET /projects`, значит меня в
 * проекте нет, и страница ответила бы 404. Пока `/me` не ответил, своё личное
 * на долю секунды выглядит как чужое — `/projects/{мой личный}` сам редиректит
 * на «Мои задачи».
 */
export type TaskProjectLabel =
  | { kind: 'personal'; text: string; to: string }
  | { kind: 'foreign-personal'; text: string; to: string }
  | { kind: 'project'; text: string; to: string | null }
  | { kind: 'unknown'; text: null; to: null }

export interface ProjectLabelContext {
  /** Имена видимых проектов по id — обычно из `useProjects()`. */
  namesById: Map<string, string>
  /** `me.personal_project_id`; `null`/`undefined` — личного проекта нет. */
  personalProjectId: string | null | undefined
}

export function taskProjectLabel(
  task: Pick<Task, 'project_id' | 'project_key' | 'project_is_personal'>,
  ctx: ProjectLabelContext,
): TaskProjectLabel {
  const to = projectLocation({
    projectId: task.project_id,
    personalProjectId: ctx.personalProjectId,
  })
  if (ctx.personalProjectId && task.project_id === ctx.personalProjectId) {
    return { kind: 'personal', text: 'Личное', to }
  }
  const name = ctx.namesById.get(task.project_id)
  if (name) return { kind: 'project', text: name, to }
  if (task.project_is_personal) {
    return { kind: 'foreign-personal', text: 'Личное коллеги', to }
  }
  // Ключ вместо имени = проекта нет в `GET /projects` = я не участник:
  // `require_project_role` прячет существование проекта 404. Чип есть,
  // ссылки нет.
  return task.project_key
    ? { kind: 'project', text: task.project_key, to: null }
    : { kind: 'unknown', text: null, to: null }
}
