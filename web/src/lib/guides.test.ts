import { describe, expect, it } from 'vitest'

import { guideRows } from './guides'
import type { Me } from '@/hooks/useMe'

function me(over: Partial<Me> = {}): Me {
  return {
    employee_id: 'e1',
    email: 'p@t.ru',
    full_name: 'Пётр',
    tenant_id: 't1',
    tenant_slug: 'uppetit',
    hub_role: 'member',
    avatar_url: '/avatar',
    profile: null,
    profile_needs_restore: false,
    can_create_projects: false,
    ...over,
  }
}

describe('guideRows', () => {
  it('отдаёт ссылки сервера как есть — порядок решает бэкенд', () => {
    const rows = guideRows(
      me({
        hub_role: 'admin',
        guides: [
          { kind: 'admin', title: 'Инструкция администратора', url: '/api/guides/admin?e=1&s=a' },
          { kind: 'employee', title: 'Инструкция сотрудника', url: '/api/guides/employee?e=1&s=b' },
        ],
      }),
    )
    expect(rows.map((r) => r.kind)).toEqual(['admin', 'employee'])
  })

  it('старый бэкенд в окне деплоя поля не отдаёт — секции просто нет', () => {
    // Не битая ссылка и не пустой блок: `guides` в ответе может отсутствовать,
    // пока сервис не перезапущен.
    expect(guideRows(me())).toEqual([])
    expect(guideRows(undefined)).toEqual([])
  })

  it('строку без url не показываем', () => {
    const rows = guideRows(
      me({
        guides: [
          { kind: 'employee', title: 'Инструкция сотрудника', url: '' },
          { kind: 'admin', title: '', url: '/api/guides/admin?e=1&s=a' },
        ],
      }),
    )
    expect(rows).toEqual([])
  })
})
