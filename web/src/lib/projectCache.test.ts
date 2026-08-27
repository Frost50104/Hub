import { describe, expect, it } from 'vitest'

import { isProjectScopedQueryKey } from './projectCache'

const ID = '3accb660-1427-4c12-9840-21890371bc50'
const OTHER = '61aec571-425c-43e8-8a8c-bffa00a0c4dd'

describe('isProjectScopedQueryKey', () => {
  it.each([
    [['projects', ID], 'детальный ответ проекта'],
    [['projects', ID, 'members'], 'участники'],
    [['tasks', ID, {}], 'список задач'],
    [['tasks', ID, 'calendar', '2026-08-01', '2026-08-31', {}], 'календарь'],
    [['stages', ID], 'колонки доски'],
    [['labels', ID, 'list'], 'метки'],
    [['labels', ID, 'assignments'], 'назначения меток'],
    [['custom-fields', 'defs', ID], 'определения кастом-полей'],
    [['custom-fields', 'project-values', ID], 'значения кастом-полей'],
    [['stats', ID], 'дашборд проекта'],
    [['timeline', ID, 'a', 'b', {}], 'хронология'],
  ])('%o — %s', (key) => {
    expect(isProjectScopedQueryKey(key, ID)).toBe(true)
  })

  it('список проектов НЕ проектный ключ — его инвалидируют, а не сносят', () => {
    expect(isProjectScopedQueryKey(['projects', { includeArchived: false }], ID)).toBe(false)
  })

  it.each([
    [['projects', OTHER], 'чужой проект'],
    [['tasks', 'detail', 'task-id'], 'карточка задачи ключуется по задаче'],
    [['task', 'task-id', 'activity'], 'лента задачи'],
    [['me-tasks'], 'мои задачи'],
    [['project-folders'], 'папки'],
    [[], 'пустой ключ'],
  ])('%o — %s, не трогаем', (key) => {
    expect(isProjectScopedQueryKey(key, ID)).toBe(false)
  })
})
