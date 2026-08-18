import { describe, expect, it } from 'vitest'

import { taskAssignees } from './taskAssignees'
import { type Task, type TaskAssigneeBrief } from './tasks'

const ANNA: TaskAssigneeBrief = {
  employee_id: 'a1',
  email: 'anna@t.ru',
  full_name: 'Анна',
}
const BORIS: TaskAssigneeBrief = {
  employee_id: 'b2',
  email: 'boris@t.ru',
  full_name: 'Борис',
}

/** Минимальная задача: интересуют только поля исполнителей. */
function task(patch: Partial<Task>): Task {
  return {
    id: 't1',
    project_id: 'p1',
    section_id: null,
    parent_task_id: null,
    title: 'Задача',
    description: null,
    status: 'todo',
    priority: 'medium',
    assignee_id: null,
    assignee: null,
    created_by: 'c1',
    start_at: null,
    due_at: null,
    position: 1,
    created_at: '',
    updated_at: '',
    completed_at: null,
    archived_at: null,
    ...patch,
  }
}

describe('taskAssignees', () => {
  it('возвращает assignees, когда сервер их прислал', () => {
    expect(taskAssignees(task({ assignees: [ANNA, BORIS] }))).toEqual([ANNA, BORIS])
  })

  it('падает на легаси-поле, если assignees нет', () => {
    // Объект из кэша, пережившего деплой, или ответ откаченного бэкенда.
    expect(taskAssignees(task({ assignee: ANNA, assignee_id: ANNA.employee_id }))).toEqual([
      ANNA,
    ])
  })

  it('возвращает пустой массив, когда нет ни того, ни другого', () => {
    expect(taskAssignees(task({}))).toEqual([])
  })

  it('пустой assignees побеждает легаси-поле (все сняты)', () => {
    expect(
      taskAssignees(task({ assignees: [], assignee: ANNA, assignee_id: ANNA.employee_id })),
    ).toEqual([])
  })
})
