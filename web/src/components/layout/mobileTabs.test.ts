import { describe, expect, it } from 'vitest'

import { LEARN_MENU_ITEMS } from './learnNav'
import { LEARN_TABS, TASK_TABS, type TabDef } from './mobileTabs'

const paths = (tabs: TabDef[]) => tabs.map((t) => (t.kind === 'link' ? t.to : `menu:${t.label}`))

describe('таб-бар «Задач»', () => {
  it('пять вкладок, ассистент на третьем месте, профиля нет', () => {
    expect(paths(TASK_TABS)).toEqual(['/', '/my', '/assistant', '/inbox', '/search'])
    expect(paths(TASK_TABS)).not.toContain('/settings')
  })
})

describe('таб-бар «Обучения»', () => {
  it('состав не изменился', () => {
    expect(paths(LEARN_TABS)).toEqual(['/learn', '/learn/courses', '/inbox', '/search', 'menu:Меню'])
  })
})

describe('подписи', () => {
  it('уникальны внутри набора — по ним ключуются вкладки', () => {
    for (const tabs of [TASK_TABS, LEARN_TABS]) {
      const labels = tabs.map((t) => t.label)
      expect(new Set(labels).size).toBe(labels.length)
    }
  })

  it('ассистент в «Меню» обучения называется так же, как вкладка', () => {
    expect(LEARN_MENU_ITEMS.find((i) => i.to === '/assistant')?.label).toBe('Ассистент')
  })
})
