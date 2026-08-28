/**
 * Перенос задачи в другой проект: куда можно и что при этом потеряется.
 *
 * Обе функции чистые ради vitest (jsdom в проекте нет) и ради того, чтобы
 * правила не жили в JSX: у списка целей четыре предиката, а у сводки — семь
 * условных строк, и в разметке такое гниёт молча.
 *
 * Сводка НЕ считает пересечения сама: их считает сервер
 * (`GET /tasks/{id}/move-preview`), здесь только текст по его отчёту. Вторая
 * реализация матчинга разошлась бы с первой на первой же правке.
 */

import { type Project } from './projects'
import { type TaskMoveReport } from './tasks'
import { plural } from './typography'

export interface MoveTarget {
  id: string
  name: string
  key: string
  isPersonal: boolean
}

/**
 * Проекты, куда эту задачу можно перенести.
 *
 * `projects` — обычный список (`GET /projects`); личного пространства в нём
 * НЕТ и не будет: сервер прячет его из всех списков проектов. Поэтому личный
 * проект приходит отдельным аргументом — точечным `GET /projects/{id}` по
 * `me.personal_project_id`. Он идёт первым: это не «ещё один проект», а другое
 * место, и искать его в алфавитном порядке незачем.
 */
export function moveTargets(
  projects: Project[] | undefined,
  personal: Project | undefined,
  currentProjectId: string,
): MoveTarget[] {
  const usable = (p: Project): boolean =>
    p.id !== currentProjectId && p.archived_at === null && p.can_edit

  const shared = (projects ?? [])
    .filter((p) => usable(p) && !p.is_personal)
    .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
    .map((p) => ({ id: p.id, name: p.name, key: p.key, isPersonal: false }))

  const own =
    personal && usable(personal)
      ? [
          {
            id: personal.id,
            name: personal.name,
            key: personal.key,
            isPersonal: true,
          },
        ]
      : []

  return [...own, ...shared]
}

/** Форма глагола под число: `plural` склоняет существительное, а «отпишутся
 *  1 наблюдатель» ломает строку ровно так же, как «1 наблюдателей». */
function verb(n: number, one: string, many: string): string {
  return n % 10 === 1 && n % 100 !== 11 ? one : many
}

export interface MoveSummary {
  /** Нейтральные последствия — списком. */
  lines: string[]
  /** То, из-за чего задачу увидят посторонние. Диалог красит отдельно. */
  warning: string | null
}

/** Текст сводки по отчёту предпросмотра. Пункты с нулём не печатаются. */
export function describeTaskMove(report: TaskMoveReport): MoveSummary {
  const lines = [`Задача получит новый номер в проекте «${report.project_name}».`]

  if (report.subtasks > 0) {
    lines.push(
      `Вместе с ней ${verb(report.subtasks, 'переедет', 'переедут')} ` +
        `${plural(report.subtasks, 'подзадача', 'подзадачи', 'подзадач')}.`,
    )
  }
  if (report.labels_total > 0) {
    lines.push(
      report.labels_kept === report.labels_total
        ? 'Метки переедут все — в новом проекте есть одноимённые.'
        : `Метки: переедет ${report.labels_kept} из ${report.labels_total} — только те, у которых в новом проекте есть одноимённая.`,
    )
  }
  if (report.values_total > 0) {
    lines.push(
      report.values_kept === report.values_total
        ? 'Значения полей переедут все.'
        : `Значения полей: переедет ${report.values_kept} из ${report.values_total}.`,
    )
  }
  if (report.watchers_dropped > 0) {
    lines.push(
      `От задачи ${verb(report.watchers_dropped, 'отпишется', 'отпишутся')} ` +
        `${plural(report.watchers_dropped, 'наблюдатель', 'наблюдателя', 'наблюдателей')}: ` +
        'в новом проекте их нет.',
    )
  }
  if (report.dependencies_dropped > 0) {
    lines.push(
      `${verb(report.dependencies_dropped, 'Снимется', 'Снимутся')} ` +
        `${plural(report.dependencies_dropped, 'связь', 'связи', 'связей')} ` +
        'с задачами прежнего проекта.',
    )
  }
  if (report.shares_revoked > 0) {
    lines.push('Публичная ссылка на задачу перестанет работать.')
  }

  return {
    lines,
    warning: report.target_public
      ? `У проекта «${report.project_name}» есть публичная ссылка — задача станет видна по ней всем, у кого она есть.`
      : null,
  }
}
