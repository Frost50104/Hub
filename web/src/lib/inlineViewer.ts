/**
 * Чем показать файл материала, не выходя из приложения.
 *
 * ОС 19.08 «документ скачивается вместо открытия»: object-URL в новой вкладке
 * Android Chrome не рендерит (та же причина, по которой уроки ушли с iframe на
 * pdf.js). Инлайн разрешаем строго по MIME: svg — исполняемый документ, и
 * показ пользовательского svg со своего origin был бы XSS-вектором.
 */
export function inlineViewerKind(mime: string | null | undefined): 'pdf' | 'image' | null {
  if (!mime) return null
  if (mime === 'application/pdf') return 'pdf'
  if (['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(mime)) return 'image'
  return null
}
