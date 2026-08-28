import { describe, expect, it } from 'vitest'

import { type Project } from './projects'
import { describeTaskMove, moveTargets } from './taskMove'
import { type TaskMoveReport } from './tasks'

function project(over: Partial<Project> & { id: string; name: string }): Project {
  return {
    key: over.name.slice(0, 2).toUpperCase(),
    description: null,
    archived_at: null,
    folder_id: null,
    created_by: 'u',
    created_at: '',
    updated_at: '',
    my_role: 'owner',
    is_favorite: false,
    can_edit: true,
    can_manage: true,
    ...over,
  } as Project
}

const REPORT: TaskMoveReport = {
  project_id: 'p',
  project_name: 'Развитие Hub',
  new_key: null,
  subtasks: 0,
  labels_kept: 0,
  labels_total: 0,
  values_kept: 0,
  values_total: 0,
  watchers_dropped: 0,
  dependencies_dropped: 0,
  shares_revoked: 0,
  target_public: false,
}

describe('moveTargets', () => {
  const current = project({ id: 'cur', name: 'Текущий' })

  it('отбрасывает текущий, архивный и тот, где нет прав', () => {
    const targets = moveTargets(
      [
        current,
        project({ id: 'ok', name: 'Годный' }),
        project({ id: 'arch', name: 'Архивный', archived_at: '2026-01-01' }),
        project({ id: 'ro', name: 'Только чтение', can_edit: false }),
      ],
      undefined,
      'cur',
    )
    expect(targets.map((t) => t.id)).toEqual(['ok'])
  })

  it('добавляет личный проект первым: в GET /projects его нет никогда', () => {
    const personal = project({ id: 'me', name: 'Личное', is_personal: true })
    const targets = moveTargets([project({ id: 'a', name: 'Альфа' })], personal, 'cur')
    expect(targets.map((t) => t.id)).toEqual(['me', 'a'])
    expect(targets[0]?.isPersonal).toBe(true)
  })

  it('не предлагает личный, когда задача уже в нём', () => {
    const personal = project({ id: 'me', name: 'Личное', is_personal: true })
    const targets = moveTargets([project({ id: 'a', name: 'Альфа' })], personal, 'me')
    expect(targets.map((t) => t.id)).toEqual(['a'])
  })

  it('переживает отсутствие списка и личного (старый бэкенд без поля)', () => {
    expect(moveTargets(undefined, undefined, 'cur')).toEqual([])
  })
})

describe('describeTaskMove', () => {
  it('о нулях молчит', () => {
    const { lines, warning } = describeTaskMove(REPORT)
    expect(lines).toHaveLength(1)
    expect(lines[0]).toContain('новый номер')
    expect(warning).toBeNull()
  })

  it('называет потерю числом, а не «часть»', () => {
    const { lines } = describeTaskMove({
      ...REPORT,
      subtasks: 4,
      labels_kept: 1,
      labels_total: 3,
      values_kept: 0,
      values_total: 1,
      watchers_dropped: 2,
      dependencies_dropped: 1,
      shares_revoked: 1,
    })
    expect(lines.join(' ')).toContain('1 из 3')
    expect(lines.join(' ')).toContain('0 из 1')
    expect(lines.some((l) => l.includes('подзадачи'))).toBe(true)
    expect(lines.some((l) => l.includes('наблюдателя'))).toBe(true)
    expect(lines.some((l) => l.includes('Публичная ссылка'))).toBe(true)
  })

  it('согласует глагол с числом: «отпишется 1», «отпишутся 2»', () => {
    const one = describeTaskMove({ ...REPORT, watchers_dropped: 1, subtasks: 1 })
    expect(one.lines.join(' ')).toContain('отпишется')
    expect(one.lines.join(' ')).toContain('переедет')
    const many = describeTaskMove({ ...REPORT, watchers_dropped: 2, subtasks: 5 })
    expect(many.lines.join(' ')).toContain('отпишутся')
    expect(many.lines.join(' ')).toContain('переедут')
    // 11 — исключение из правила «оканчивается на 1»
    const eleven = describeTaskMove({ ...REPORT, watchers_dropped: 11 })
    expect(eleven.lines.join(' ')).toContain('отпишутся')
  })

  it('не пугает, когда всё переезжает целиком', () => {
    const { lines } = describeTaskMove({
      ...REPORT,
      labels_kept: 2,
      labels_total: 2,
    })
    expect(lines.join(' ')).not.toContain('из 2')
  })

  it('публичную ссылку цели выносит в предупреждение, а не в список', () => {
    const { lines, warning } = describeTaskMove({ ...REPORT, target_public: true })
    expect(lines).toHaveLength(1)
    expect(warning).toContain('станет видна')
  })
})
