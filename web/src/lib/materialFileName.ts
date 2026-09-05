/** Имя файла материала для системной шторки «Поделиться» (iOS PWA).
 *
 *  `current_version.file_name` — источник истины, но WEEEK-импорт оставил
 *  артефакты вида `file_name="xlsx"` (имя обрезано до расширения): без точки
 *  внутри имя собирается из НАЗВАНИЯ материала + расширения по mime — иначе
 *  человек сохранял бы файл «xlsx» без намёка, что это за бланк.
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
}

export function materialDownloadName(material: LibraryMaterial): string {
  const stored = material.current_version?.file_name?.trim() ?? ''
  // Точка не первой позицией: «.hidden» или «xlsx» — не имя с расширением.
  if (stored.length > 1 && stored.includes('.') && !stored.startsWith('.')) return stored
  const ext = MIME_EXT[material.current_version?.mime ?? '']
  // Символы, запрещённые в именах файлов, — в пробел; остальное iOS переживает.
  const base =
    (material.title || 'файл').replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim() ||
    'файл'
  return ext ? `${base}.${ext}` : base
}
