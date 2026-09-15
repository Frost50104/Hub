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

import { type Task } from './tasks'

export type TaskProjectLabel =
  | { kind: 'personal'; text: string }
  | { kind: 'foreign-personal'; text: string }
  | { kind: 'project'; text: string }
  | { kind: 'unknown'; text: null }

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
  if (ctx.personalProjectId && task.project_id === ctx.personalProjectId) {
    return { kind: 'personal', text: 'Личное' }
  }
  const name = ctx.namesById.get(task.project_id)
  if (name) return { kind: 'project', text: name }
  if (task.project_is_personal) {
    return { kind: 'foreign-personal', text: 'Личное коллеги' }
  }
  return task.project_key
    ? { kind: 'project', text: task.project_key }
    : { kind: 'unknown', text: null }
}
