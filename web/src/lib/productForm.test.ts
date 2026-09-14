import { describe, expect, it } from 'vitest'

import {
  canEditProductAudience,
  canPublishProduct,
  canSaveProduct,
  productStatusActions,
} from './productForm'

describe('canPublishProduct', () => {
  it('публикуют только publisher и admin — зеркало матрицы lifecycle', () => {
    expect(canPublishProduct('publisher')).toBe(true)
    expect(canPublishProduct('admin')).toBe(true)
    expect(canPublishProduct('author')).toBe(false)
    expect(canPublishProduct('none')).toBe(false)
  })

  it('аудитория — то же право: ручка требует publisher', () => {
    expect(canEditProductAudience('author')).toBe(false)
    expect(canEditProductAudience('publisher')).toBe(true)
  })
})

describe('productStatusActions', () => {
  it('автору кнопок не даёт: сервер ответил бы 403 после клика', () => {
    expect(productStatusActions('author', 'draft')).toEqual([])
    expect(productStatusActions('none', 'published')).toEqual([])
  })

  it('черновик и «на согласовании» публикуются', () => {
    expect(productStatusActions('publisher', 'draft')).toEqual([
      { to: 'published', label: 'Опубликовать' },
    ])
    expect(productStatusActions('admin', 'review')).toEqual([
      { to: 'published', label: 'Опубликовать' },
    ])
  })

  it('опубликованное только архивируется — перехода published→draft в матрице нет', () => {
    expect(productStatusActions('publisher', 'published')).toEqual([
      { to: 'archived', label: 'В архив' },
    ])
  })

  it('из архива возвращают в публикацию', () => {
    expect(productStatusActions('publisher', 'archived')).toEqual([
      { to: 'published', label: 'Вернуть из архива' },
    ])
  })
})

describe('canSaveProduct', () => {
  it('пустое и пробельное название не сохраняем — зеркало 422', () => {
    expect(canSaveProduct('')).toBe(false)
    expect(canSaveProduct('   ')).toBe(false)
    expect(canSaveProduct('Латте 250')).toBe(true)
  })
})
