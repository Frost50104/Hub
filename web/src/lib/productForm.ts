import type { ContentStatus } from '@/lib/learn'

/**
 * Карточка товара: что можно сохранить и какие переходы показывать кнопками.
 *
 * Правила вынесены из разметки, потому что они — ЗЕРКАЛО СЕРВЕРА. Пока они
 * жили тернарником в JSX, кнопку «Опубликовать» видел любой, кто ведёт
 * контент, а `lifecycle.transition` отвечал автору 403 «Недостаточно прав для
 * этого перехода» — отказ приходил в конце пути, после заполненной формы. Та
 * же история у кнопки «Аудитория»: ручка требует publisher.
 *
 * Источник истины — матрица `app/services/lifecycle.py::_ALLOWED`:
 *   draft→review     author      (кнопки в ассортименте нет и не было)
 *   draft→published  publisher
 *   published→archived, archived→published, archived→draft — publisher
 * Ролей четыре: none | author | publisher | admin.
 */

export function canManageProducts(role: string): boolean {
  return ['admin', 'publisher', 'author'].includes(role)
}

/** Зеркало ('draft','published'): 'publisher' — публикует publisher и выше. */
export function canPublishProduct(role: string): boolean {
  return ['admin', 'publisher'].includes(role)
}

/** Зеркало require_content_role(..., "publisher") в set_product_audience. */
export const canEditProductAudience = canPublishProduct

export interface ProductStatusAction {
  to: 'published' | 'archived'
  label: string
}

/**
 * Какие переходы статуса показывать кнопками. Пустой массив — кнопок нет.
 *
 * Перехода published→draft в матрице нет: «снять с публикации» — это архив,
 * и предлагать иное значило бы обещать несуществующее.
 */
export function productStatusActions(
  role: string,
  status: ContentStatus,
): ProductStatusAction[] {
  if (!canPublishProduct(role)) return []
  if (status === 'published') return [{ to: 'archived', label: 'В архив' }]
  if (status === 'archived') return [{ to: 'published', label: 'Вернуть из архива' }]
  return [{ to: 'published', label: 'Опубликовать' }] // draft | review
}

/** Зеркало 422 «Название обязательно» (app/api/products.py). */
export function canSaveProduct(title: string): boolean {
  return title.trim().length > 0
}
