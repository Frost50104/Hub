/**
 * Чем показать файл материала, не выходя из приложения.
 *
 * ОС 19.08 «документ скачивается вместо открытия»: object-URL в новой вкладке
 * Android Chrome не рендерит (та же причина, по которой уроки ушли с iframe на
 * pdf.js). Инлайн разрешаем строго по MIME: svg — исполняемый документ, и
 * показ пользовательского svg со своего origin был бы XSS-вектором.
 *
 * ОС 2026-08: для docx/xlsx (две трети библиотеки) кнопка «Открыть документ»
 * на деле скачивала — теперь главное действие называется честно
 * (`materialPrimaryAction`), а текст таких файлов показывает «Просмотреть
 * текст» (извлечённый воркером).
 */
export function inlineViewerKind(mime: string | null | undefined): 'pdf' | 'image' | null {
  if (!mime) return null
  if (mime === 'application/pdf') return 'pdf'
  if (['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(mime)) return 'image'
  return null
}

const TEXT_PREVIEW_MIMES = new Set([
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
])

/** docx/xlsx — текст извлекает воркер; старые .doc/.xls/.ppt — нет парсера. */
export function hasTextPreview(mime: string | null | undefined): boolean {
  return !!mime && TEXT_PREVIEW_MIMES.has(mime)
}

export interface MaterialPrimaryAction {
  mode: 'link' | 'inline' | 'download'
  label: string
  /** Подсказка под кнопкой для форматов, которые браузер не показывает. */
  hint?: string
}

/** Главная кнопка карточки материала — честно по тому, что произойдёт. */
export function materialPrimaryAction(
  kind: 'file' | 'link',
  mime: string | null | undefined,
): MaterialPrimaryAction {
  if (kind === 'link') return { mode: 'link', label: 'Открыть ссылку' }
  if (inlineViewerKind(mime)) return { mode: 'inline', label: 'Открыть документ' }
  return {
    mode: 'download',
    label: 'Скачать файл',
    hint: 'Word и Excel открываются во внешнем приложении. Отметка «Ознакомлен» станет доступна после скачивания.',
  }
}
