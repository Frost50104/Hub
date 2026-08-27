/**
 * Что можно приложить и как назвать размер — БЕЗ axios и DOM.
 *
 * Отдельный модуль, потому что `lib/attachments.ts` тянет `api` (там же
 * скачивание через synthetic `<a download>`), а vitest в этом проекте бежит
 * без jsdom: любой тест на эти правила падал бы на `window is not defined`.
 * Правила зеркалят сервер, значит они обязаны быть под тестом.
 */

/** ЗЕРКАЛО серверного whitelist (app/services/attachments.py::ALLOWED_MIME) —
 * менять ПАРОЙ. SVG запрещён намеренно (stored XSS). Сервер — истина:
 * accept и клиентская проверка лишь дают понятную ошибку до запроса. */
export const ALLOWED_EXTENSIONS = [
  '.png',
  '.jpg',
  '.jpeg',
  '.webp',
  '.gif',
  '.heic',
  '.heif',
  '.pdf',
  '.zip',
  '.doc',
  '.docx',
  '.xls',
  '.xlsx',
  '.ppt',
  '.pptx',
  '.txt',
  '.md',
  '.csv',
  '.json',
] as const

export const ATTACHMENT_ACCEPT = ALLOWED_EXTENSIONS.join(',')

export const ATTACHMENT_TYPES_HUMAN =
  'изображения (PNG, JPG, WebP, GIF, HEIC), PDF, документы Office, архивы ZIP, текст (TXT, MD, CSV, JSON)'

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

/** Расширение файла в нижнем регистре, с точкой; '' если его нет. */
export function fileExtension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot).toLowerCase() : ''
}

/** null — файл проходит; иначе готовое сообщение об ошибке для тоста. */
export function attachmentTypeError(file: { name: string }): string | null {
  if ((ALLOWED_EXTENSIONS as readonly string[]).includes(fileExtension(file.name))) {
    return null
  }
  return `Файл «${file.name}» не поддерживается. Можно загружать: ${ATTACHMENT_TYPES_HUMAN}.`
}
