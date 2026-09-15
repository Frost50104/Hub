import { describe, expect, it } from 'vitest'

import { taskProjectLabel } from './taskProjectLabel'

const ctx = (names: [string, string][] = []) => ({
  namesById: new Map(names),
  personalProjectId: 'mine',
})

const task = (over: Partial<Parameters<typeof taskProjectLabel>[0]> = {}) => ({
  project_id: 'work',
  project_key: 'PLP',
  project_is_personal: false,
  ...over,
})

describe('taskProjectLabel', () => {
  it('своё личное подписывает «Личное», а не именем проекта', () => {
    // Живое имя проекта теперь «Мои задачи» — на экране с тем же заголовком
    // колонка «Проект» говорила бы «Мои задачи».
    const got = taskProjectLabel(task({ project_id: 'mine' }), ctx())
    expect(got).toEqual({ kind: 'personal', text: 'Личное', to: '/my?tab=personal' })
  })

  it('обычный проект — по имени из списка, чип ведёт на страницу проекта', () => {
    const got = taskProjectLabel(task(), ctx([['work', 'Подбор персонала']]))
    expect(got.text).toBe('Подбор персонала')
    expect(got.to).toBe('/projects/work')
  })

  it('чужое личное НЕ называет владельца', () => {
    // Раньше тут печатался project_key: «LICNOE26» был безлик, а «IVANOV»
    // после перевыдачи ключей назвал бы фамилию.
    const got = taskProjectLabel(
      task({ project_id: 'hers', project_key: 'IVANOV', project_is_personal: true }),
      ctx(),
    )
    // Ссылка есть: чужое личное видно только исполнителю и наблюдателю, а они
    // участники — страница откроется как «Личное · Имя».
    expect(got).toEqual({
      kind: 'foreign-personal',
      text: 'Личное коллеги',
      to: '/projects/hers',
    })
  })

  it('проект, из которого меня убрали, остаётся проектом — но БЕЗ ссылки', () => {
    // Задача видна, проекта в списке нет — но это НЕ личное (на проде таких 19).
    // Не участнику сервер отвечает 404, чип-ссылка вела бы в ошибку.
    const got = taskProjectLabel(task({ project_id: 'gone' }), ctx())
    expect(got).toEqual({ kind: 'project', text: 'PLP', to: null })
  })

  it('старый бэкенд без project_is_personal не врёт', () => {
    const got = taskProjectLabel(
      task({ project_id: 'gone', project_is_personal: null, project_key: null }),
      ctx(),
    )
    expect(got).toEqual({ kind: 'unknown', text: null, to: null })
  })
})
