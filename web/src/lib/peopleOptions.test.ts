import { describe, expect, it } from 'vitest'

import { mergeSelected, personLabel } from './peopleOptions'
import { type TaskAssigneeBrief } from './tasks'
import { type TenantMember } from './tenant'

const brief = (id: string, name = ''): TaskAssigneeBrief => ({
  employee_id: id,
  email: `${id}@uppetit.ru`,
  full_name: name,
})

const member = (id: string, name = ''): TenantMember => ({
  employee_id: id,
  email: `${id}@uppetit.ru`,
  full_name: name,
  handle: id,
  mention: name ? name.replace(/ /g, '_') : id,
})

describe('mergeSelected', () => {
  it('выбранные идут первыми', () => {
    const out = mergeSelected([brief('a', 'Анна')], [member('b', 'Борис')])
    expect(out.map((p) => p.employee_id)).toEqual(['a', 'b'])
  })

  it('выбранный не дублируется, даже если пришёл в выдаче', () => {
    const out = mergeSelected([brief('a', 'Анна')], [member('a', 'Анна'), member('b')])
    expect(out.map((p) => p.employee_id)).toEqual(['a', 'b'])
  })

  it('выбранный остаётся, когда поиск его не вернул', () => {
    // Иначе снять человека можно было бы, только найдя его по фамилии.
    const out = mergeSelected([brief('a', 'Анна')], [member('z', 'Зоя')])
    expect(out.map((p) => p.employee_id)).toEqual(['a', 'z'])
  })

  it('пустые входы не роняют', () => {
    expect(mergeSelected([], [])).toEqual([])
  })
})

describe('personLabel', () => {
  it('имя в приоритете, почта — запасной вариант', () => {
    expect(personLabel(brief('a', 'Анна Белова'))).toBe('Анна Белова')
    expect(personLabel(brief('a'))).toBe('a@uppetit.ru')
  })

  it('без имени и почты остаётся id — строка никогда не пустая', () => {
    expect(personLabel({ employee_id: 'a', email: '', full_name: '' })).toBe('a')
  })
})
