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
  '.mp4',
  '.mov',
  '.webm',
] as const

/**
 * Видео (ОС 15.09). Три контейнера покрывают то, чем снимают на деле: Android
 * и запись экрана дают mp4, iPhone — mov, браузерная запись — webm.
 *
 * Вид файла определяем по РАСШИРЕНИЮ, а не по `file.type`: браузер часто не
 * знает тип и отдаёт пустую строку или `application/octet-stream` — ровно
 * поэтому на сервере есть карта восстановления `_EXT_FALLBACK_MIME`. Опираться
 * здесь на `file.type` значило бы применить к видео лимит документа и не
 * пустить его до сервера, который его как раз принял бы.
 */
export const VIDEO_EXTENSIONS: readonly string[] = ['.mp4', '.mov', '.webm']

export const ATTACHMENT_ACCEPT = ALLOWED_EXTENSIONS.join(',')

export const ATTACHMENT_TYPES_HUMAN =
  'изображения (PNG, JPG, WebP, GIF, HEIC), видео (MP4, MOV, WebM), PDF, ' +
  'документы Office, архивы ZIP, текст (TXT, MD, CSV, JSON)'

/** Зеркало `attachment_max_bytes` (app/config.py). */
export const ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024
/** Зеркало `attachment_video_max_bytes`: минута 1080p с телефона ≈ 100 МБ. */
export const ATTACHMENT_VIDEO_MAX_BYTES = 1024 * 1024 * 1024

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  // Гигабайты появились вместе с видео: «1024.0 МБ» в тексте отказа читается
  // как ошибка вёрстки, а не как лимит.
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} ГБ`
}

/** Расширение файла в нижнем регистре, с точкой; '' если его нет. */
export function fileExtension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot).toLowerCase() : ''
}

export function isVideoFile(name: string): boolean {
  return VIDEO_EXTENSIONS.includes(fileExtension(name))
}

/** Зеркало `attachments.py::attachment_size_limit` — менять ПАРОЙ. */
export function attachmentSizeLimit(name: string): number {
  return isVideoFile(name) ? ATTACHMENT_VIDEO_MAX_BYTES : ATTACHMENT_MAX_BYTES
}

/** null — файл проходит; иначе готовое сообщение об ошибке для тоста. */
export function attachmentTypeError(file: { name: string }): string | null {
  if ((ALLOWED_EXTENSIONS as readonly string[]).includes(fileExtension(file.name))) {
    return null
  }
  return `Файл «${file.name}» не поддерживается. Можно загружать: ${ATTACHMENT_TYPES_HUMAN}.`
}

/**
 * null — размер в порядке; иначе текст отказа.
 *
 * Проверяем до запроса: гигабайтный лимит живёт в отдельной nginx-локации, и
 * файл сверх него обрывается посреди загрузки голым 413 без внятного текста —
 * после того, как человек уже подождал.
 */
export function attachmentSizeError(file: { name: string; size: number }): string | null {
  const limit = attachmentSizeLimit(file.name)
  if (file.size <= limit) return null
  return `«${file.name}» больше ${formatBytes(limit)} — не загрузится`
}
