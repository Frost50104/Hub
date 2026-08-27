import { describe, expect, it } from 'vitest'

import { folderDeleteWarning } from './folderActions'

describe('folderDeleteWarning', () => {
  it('пустая папка', () => {
    expect(folderDeleteWarning(0)).toBe('Папка пуста.')
  })

  it('непустая обещает сохранить проекты', () => {
    expect(folderDeleteWarning(3)).toContain('останутся')
    expect(folderDeleteWarning(3)).toContain('(3)')
  })
})
