import { BookOpen, CircleX, Info, Lightbulb, ThumbsUp, TriangleAlert } from 'lucide-react'

/**
 * Метаданные callout-блоков БЕЗ импортов TipTap — их использует read-only
 * RichRenderer, который не должен тянуть ProseMirror в чанки прохождения
 * контента (инвариант плана). lucide-react импортировать можно: он уже в
 * рендер-пути и ProseMirror за собой не тянет.
 *
 * Emoji убраны (редизайн): бренд их не использует. Тип выноски несут иконка
 * и цветная левая полоса 3px, а ярлык набирается --text2 — амбер-текст даёт
 * 1,64:1 в светлой теме, красный 4,18:1 при норме 4,5:1.
 */

export type CalloutKind =
  | 'important'
  | 'warning'
  | 'tip'
  | 'mistake'
  | 'example'
  | 'recommendation'

export interface CalloutMeta {
  label: string
  icon: typeof Info
  /** Рамка + левая полоса + фон контейнера. Цвет типа несёт левая полоса. */
  box: string
}

export const CALLOUT_META: Record<CalloutKind, CalloutMeta> = {
  important: {
    label: 'Важно',
    icon: Info,
    box: 'border-amber/35 border-l-amber bg-amber/[0.09]',
  },
  warning: {
    label: 'Внимание',
    icon: TriangleAlert,
    box: 'border-red/35 border-l-red bg-red/[0.09]',
  },
  tip: {
    label: 'Совет',
    icon: Lightbulb,
    box: 'border-green/35 border-l-green bg-green/[0.09]',
  },
  mistake: {
    label: 'Частая ошибка',
    icon: CircleX,
    box: 'border-red/[0.28] border-l-red/60 bg-red/[0.05]',
  },
  example: {
    label: 'Пример',
    icon: BookOpen,
    box: 'border-hair border-l-text3 bg-surface',
  },
  recommendation: {
    label: 'Рекомендация',
    icon: ThumbsUp,
    box: 'border-amber/[0.22] border-l-amber/50 bg-surface',
  },
}
