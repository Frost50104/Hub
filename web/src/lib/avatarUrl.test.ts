import { describe, expect, it } from 'vitest'

import { avatarUrl } from './avatarUrl'

describe('avatarUrl', () => {
  it('строит адрес фото по employee_id', () => {
    expect(avatarUrl('79c92fc0-3b0c-46ed-83a0-d40c53d660e3')).toBe(
      'https://auth.signaris.ru/api/avatars/79c92fc0-3b0c-46ed-83a0-d40c53d660e3',
    )
  })

  it('без id адреса нет — Avatar покажет инициалы', () => {
    // `employee_id` бывает null: в срезе загрузки по людям это строка
    // «Не назначено» (ProjectDashboard), и запрашивать по ней нечего.
    expect(avatarUrl(null)).toBeUndefined()
    expect(avatarUrl(undefined)).toBeUndefined()
    expect(avatarUrl('')).toBeUndefined()
  })
})
