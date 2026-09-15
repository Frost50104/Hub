/** Имя файла материала для системной шторки «Поделиться» (iOS PWA) и для
 *  запасного `<a download>`.
 *
 *  `current_version.file_name` — источник истины, но в колонке живут
 *  искалеченные имена: ASCII-санитайзер загрузки срезал кириллицу целиком, и
 *  от «ЛДМО.xlsx» оставалось «xlsx» (на проде так у 58 материалов). Такой
 *  файл скачивался как «xlsx.xlsx» или вовсе без расширения — Windows его не
 *  открывает (ОС 14.09). Поэтому имя без точки внутри собирается из НАЗВАНИЯ
 *  материала и расширения: по mime, а если mime незнаком — из самой
 *  испорченной строки.
 *
 *  ЗЕРКАЛО сервера: `app/services/attachments.py::download_filename`. Сервер
 *  чинит имя в Content-Disposition, здесь — имя для `navigator.share`;
 *  правила обязаны совпадать, иначе один и тот же файл сохранится под разными
 *  именами на телефоне и на компьютере.
 *
 *  Чистая функция ради vitest (jsdom в проекте нет).
 */

import type { LibraryMaterial } from '@/lib/learn'

const MIME_EXT: Record<string, string> = {
  'application/pdf': 'pdf',
  'application/msword': 'doc',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
  'application/vnd.ms-excel': 'xls',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
  'application/vnd.ms-powerpoint': 'ppt',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/webp': 'webp',
  'text/plain': 'txt',
  'text/markdown': 'md',
  'text/csv': 'csv',
  'image/gif': 'gif',
  'image/heic': 'heic',
  'image/heif': 'heif',
}

const BARE_EXT = /^[A-Za-z0-9]{1,5}$/

export function materialDownloadName(material: LibraryMaterial): string {
  const stored = material.current_version?.file_name?.trim() ?? ''
  // Точка не первой позицией: «.hidden» или «xlsx» — не имя с расширением.
  if (stored.length > 1 && stored.includes('.') && !stored.startsWith('.')) return stored
  const ext =
    MIME_EXT[material.current_version?.mime ?? ''] ??
    (BARE_EXT.test(stored) ? stored.toLowerCase() : undefined)
  // Символы, запрещённые в именах файлов, — в пробел; хвостовые точки и
  // пробелы Windows всё равно не сохранит.
  const base =
    (material.title || 'файл')
      .replace(/[\\/:*?"<>|]+/g, ' ')
      .replace(/\s+/g, ' ')
      .replace(/\s+(?=\.)/g, '')
      .trim()
      .replace(/[. ]+$/, '') || 'файл'
  return ext ? `${base}.${ext}` : base
}
