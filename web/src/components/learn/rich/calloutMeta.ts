/**
 * Метаданные callout-блоков БЕЗ импортов TipTap — их использует read-only
 * RichRenderer, который не должен тянуть ProseMirror в чанки прохождения
 * контента (инвариант плана).
 */

export type CalloutKind =
  | 'important'
  | 'warning'
  | 'tip'
  | 'mistake'
  | 'example'
  | 'recommendation'

export const CALLOUT_META: Record<CalloutKind, { label: string; emoji: string }> = {
  important: { label: 'Важно', emoji: '❗' },
  warning: { label: 'Внимание', emoji: '⚠️' },
  tip: { label: 'Совет', emoji: '💡' },
  mistake: { label: 'Ошибка', emoji: '❌' },
  example: { label: 'Пример', emoji: '📝' },
  recommendation: { label: 'Рекомендация', emoji: '👍' },
}
