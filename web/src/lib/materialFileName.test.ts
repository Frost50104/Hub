import { describe, expect, it } from 'vitest'

import type { LibraryMaterial } from './learn'

import { materialDownloadName } from './materialFileName'

function mat(fileName: string | null, mime: string, title = 'Бланк заказа: Dessert Fantasy') {
  return {
    title,
    current_version: fileName === null ? null : { file_name: fileName, mime },
  } as unknown as LibraryMaterial
}

const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

describe('materialDownloadName', () => {
  it('нормальное имя версии отдаётся как есть', () => {
    expect(materialDownloadName(mat('заказ.xlsx', XLSX))).toBe('заказ.xlsx')
  })

  it('WEEEK-артефакт «xlsx» без точки → имя из названия + расширение по mime', () => {
    expect(materialDownloadName(mat('xlsx', XLSX))).toBe(
      'Бланк заказа Dessert Fantasy.xlsx',
    )
  })

  it('неизвестный mime — без расширения; запрещённые символы вычищены', () => {
    expect(materialDownloadName(mat('', 'application/x-unknown', 'A/B: «C»?'))).toBe(
      'A B «C»',
    )
  })

  it('версии нет вовсе — не падаем', () => {
    expect(materialDownloadName(mat(null, ''))).toBe('Бланк заказа Dessert Fantasy')
  })
})
