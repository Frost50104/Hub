import { describe, expect, it } from 'vitest'

import { IMPORT_DIALOG_HINT, importReportLine, importToastText } from './employeeImport'

describe('employeeImport', () => {
  it('отчёт говорит «обновлено», а не «создано» — импорт карточек не заводит', () => {
    expect(importReportLine({ updated: 3, skipped: 1, errors: [], dry_run: true })).toBe(
      'Проверка (без сохранения): обновлено 3, пропущено 1',
    )
    expect(importReportLine({ updated: 3, skipped: 1, errors: [], dry_run: false })).toBe(
      'Результат: обновлено 3, пропущено 1',
    )
    expect(importToastText({ updated: 0, skipped: 2, errors: [], dry_run: false })).toBe(
      'Импорт завершён: обновлено 0, пропущено 2',
    )
  })

  it('подсказка диалога называет auth источником карточек и не обещает создать точки', () => {
    expect(IMPORT_DIALOG_HINT).toContain('заводятся в auth')
    expect(IMPORT_DIALOG_HINT).not.toContain('создадутся автоматически')
    expect(IMPORT_DIALOG_HINT).toContain('Неизвестная точка — ошибка')
  })
})
