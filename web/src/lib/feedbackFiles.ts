/**
 * Набор файлов формы обратной связи: что принимаем и как объясняем отказ.
 *
 * Отдельно от `feedback.ts`, который тянет axios: правил четыре (тип, размер
 * файла, суммарный вес, количество), каждое зеркалит сервер — и все обязаны
 * быть под тестом, а vitest здесь бежит без jsdom.
 */

import {
  ATTACHMENT_ACCEPT,
  fileExtension,
  formatBytes,
} from './attachmentTypes'

/** Столько же, сколько принимает сервер (`app/api/feedback.py::TEXT_MAX`). */
export const FEEDBACK_TEXT_MAX = 5000
/** Зеркало `attachment_max_bytes`: 20 МБ. */
const FEEDBACK_FILE_MAX = 20 * 1024 * 1024
/** Зеркало `MAX_FILES` ручки — менять ПАРОЙ, иначе форма пустит в 422. */
export const FEEDBACK_FILES_MAX = 10
/** Зеркало `TOTAL_BYTES_MAX`: 50 МБ на всю отправку. */
export const FEEDBACK_TOTAL_MAX = 50 * 1024 * 1024

export { ATTACHMENT_ACCEPT as FEEDBACK_ACCEPT }

/**
 * Проверка файла ДО запроса — чтобы человек увидел причину, а не голый 415.
 * Сервер проверяет то же самое и остаётся истиной (`services/attachments.py`).
 */
export function feedbackFileError(file: File): string | null {
  if (file.size > FEEDBACK_FILE_MAX) {
    return `Файл больше ${formatBytes(FEEDBACK_FILE_MAX)} — прикрепите что-то полегче`
  }
  const ext = fileExtension(file.name)
  if (!ext || !ATTACHMENT_ACCEPT.split(',').includes(ext)) {
    return 'Такой тип файла приложить нельзя — подойдут картинка, PDF или документ'
  }
  return null
}

/**
 * Как отличить два одинаково названных файла.
 *
 * Не по одному имени: «screenshot.png» с рабочего стола и из загрузок — разные
 * файлы, и отбросить второй значит потерять половину бага. Имя + размер +
 * время правки различают их и при этом ловят настоящий повтор — когда человек
 * выбрал тот же файл дважды.
 */
function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`
}

export interface FeedbackFilesResult {
  files: File[]
  /** Причины, по которым что-то не взяли, — по одной строке на человека. */
  errors: string[]
}

/**
 * Добавить выбранные файлы к уже набранным.
 *
 * Вся арифметика набора — здесь, а не в обработчике `onChange`: правил четыре
 * (тип, размер файла, суммарный вес, количество), и каждое должно объяснять
 * себя человеку. Молча отброшенный файл выглядит как «форма съела скриншот».
 */
export function addFeedbackFiles(current: File[], incoming: File[]): FeedbackFilesResult {
  const files = [...current]
  const errors: string[] = []
  const seen = new Set(files.map(fileKey))
  let total = files.reduce((sum, f) => sum + f.size, 0)

  for (const file of incoming) {
    if (seen.has(fileKey(file))) continue // тот же файл выбрали дважды — молча
    const problem = feedbackFileError(file)
    if (problem) {
      errors.push(`${file.name}: ${problem}`)
      continue
    }
    if (files.length >= FEEDBACK_FILES_MAX) {
      errors.push(`Больше ${FEEDBACK_FILES_MAX} файлов за раз не отправить`)
      break
    }
    if (total + file.size > FEEDBACK_TOTAL_MAX) {
      errors.push(
        `${file.name}: вместе файлы весят больше ${formatBytes(FEEDBACK_TOTAL_MAX)}`,
      )
      continue
    }
    files.push(file)
    seen.add(fileKey(file))
    total += file.size
  }
  return { files, errors }
}

/** Суммарный вес набора — для подписи под списком. */
export function feedbackFilesSize(files: readonly File[]): number {
  return files.reduce((sum, f) => sum + f.size, 0)
}
