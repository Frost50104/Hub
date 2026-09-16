/** Тексты диалога CSV-импорта сотрудников (update-only с 16.09).
 *
 *  Импорт больше не создаёт карточек: учётные записи и карточки заводятся в
 *  auth, а CSV только обновляет HR-поля существующих. Строки без карточки
 *  сервер отдаёт построчными ошибками. Чистый модуль ради vitest — как
 *  `authState.ts`.
 */

import type { ImportReport } from './learn'

export const IMPORT_DIALOG_HINT =
  'Колонки: email (ключ), phone, position, store, department, franchisee, ' +
  'org_role, manager_email, hired_at. Разделитель — «;» или «,». Обновляются ' +
  'существующие карточки, пустые ячейки поля не трогают; строки без карточки ' +
  'пропускаются — учётные записи заводятся в auth. Неизвестная точка — ошибка ' +
  'строки, должности и отделы создаются. Смена должности или точки может ' +
  'разослать назначения обязательных курсов — сначала «Проверить».'

export function importReportLine(report: ImportReport): string {
  const head = report.dry_run ? 'Проверка (без сохранения):' : 'Результат:'
  return `${head} обновлено ${report.updated}, пропущено ${report.skipped}`
}

export function importToastText(report: ImportReport): string {
  return `Импорт завершён: обновлено ${report.updated}, пропущено ${report.skipped}`
}
