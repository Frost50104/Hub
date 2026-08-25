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

  it('подпись строки — целиком, без второй надписи справа', () => {
    // У админа две строки, и раньше они отличались только мелким текстом
    // сбоку: обе начинались с «Посмотреть инструкцию».
    const rows = guideRows(
      me({
        hub_role: 'admin',
        guides: [
          { kind: 'admin', title: 'Инструкция администратора', url: '/a?e=1&s=a' },
          { kind: 'employee', title: 'Инструкция сотрудника', url: '/e?e=1&s=b' },
        ],
      }),
    )
    expect(rows.map((r) => r.label)).toEqual([
      'Посмотреть инструкцию для администратора',
      'Посмотреть инструкцию',
    ])
  })

  it('незнакомый вид подписывается по названию документа', () => {
    const rows = guideRows(
      me({ guides: [{ kind: 'tu', title: 'Инструкция ТУ', url: '/t?e=1&s=c' }] }),
    )
    expect(rows[0]!.label).toBe('Посмотреть: Инструкция ТУ')
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
