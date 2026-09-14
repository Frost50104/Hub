import { describe, expect, it } from 'vitest'

import { decideThemeSync, type ThemeSyncInput } from './themeSync'

const ME = 'emp-a'
const OTHER = 'emp-b'

const input = (over: Partial<ThemeSyncInput> = {}): ThemeSyncInput => ({
  serverTheme: null,
  localTheme: null,
  localOwner: null,
  employeeId: ME,
  currentTheme: 'dark',
  ...over,
})

describe('decideThemeSync', () => {
  it('поля нет в ответе — синхронизации нет (старый бэкенд, dev-стенд)', () => {
    expect(
      decideThemeSync(input({ serverTheme: undefined, localTheme: 'light' })),
    ).toEqual({ kind: 'none' })
  })

  it('серверная тема побеждает кеш устройства', () => {
    expect(
      decideThemeSync(input({ serverTheme: 'light', localTheme: 'dark' })),
    ).toEqual({ kind: 'adopt', theme: 'light' })
  })

  it('серверная тема применяется и когда кеш пуст', () => {
    expect(decideThemeSync(input({ serverTheme: 'light' }))).toEqual({
      kind: 'adopt',
      theme: 'light',
    })
  })

  it('уже покрашено нами — ничего не делаем', () => {
    expect(
      decideThemeSync(
        input({ serverTheme: 'dark', currentTheme: 'dark', localOwner: ME }),
      ),
    ).toEqual({ kind: 'none' })
  })

  it('тема совпала, но кеш чужой — применяем, чтобы перетегировать устройство', () => {
    expect(
      decideThemeSync(
        input({ serverTheme: 'dark', currentTheme: 'dark', localOwner: OTHER }),
      ),
    ).toEqual({ kind: 'adopt', theme: 'dark' })
  })

  it('на сервере пусто, кеш свой — засеваем выбор, сделанный до выката', () => {
    expect(
      decideThemeSync(input({ serverTheme: null, localTheme: 'light' })),
    ).toEqual({ kind: 'seed', theme: 'light' })
    expect(
      decideThemeSync(
        input({ serverTheme: null, localTheme: 'light', localOwner: ME }),
      ),
    ).toEqual({ kind: 'seed', theme: 'light' })
  })

  it('на сервере пусто, а кеш ЧУЖОЙ — не засеваем (иначе баг переедет в БД)', () => {
    expect(
      decideThemeSync(
        input({ serverTheme: null, localTheme: 'light', localOwner: OTHER }),
      ),
    ).toEqual({ kind: 'none' })
  })

  it('на сервере пусто и тему никогда не выбирали — засевать нечего', () => {
    expect(decideThemeSync(input({ serverTheme: null, localTheme: null }))).toEqual({
      kind: 'none',
    })
  })
})
