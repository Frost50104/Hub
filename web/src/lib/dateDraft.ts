/**
 * Черновик даты и времени в карточке задачи — когда синхронизировать с
 * сервером и что делать при уходе фокуса.
 *
 * Почему черновик, а не сохранение на каждый `onChange`, как было: набор с
 * клавиатуры шлёт промежуточные значения (год «2027» → `0002 → 0020 → 0202 →
 * 2027`, время «1530» → `15:03 → 15:30`, перенабор дня — пустую строку; замер
 * в Chrome 24.09), и каждое уходило PATCH-ем. С личными напоминаниями,
 * которые следуют за сроком (0062), это ещё и перевзводило бы их по кругу.
 *
 * Правила чистые (vitest без jsdom): компонент только зовёт их.
 */

import { type DateTimeValue, sameDateTime } from '@/lib/taskDateTime'

export interface DateDraft {
  value: DateTimeValue
  /** Человек менял поле и ещё не сохранил. */
  dirty: boolean
}

/**
 * Пришло новое значение с сервера (оптимистичный патч, перезапрос после любой
 * правки задачи, фокус окна). Несохранённый ввод НЕ перетираем — иначе
 * перезапрос после правки времени затирал бы дату, которую человек как раз
 * набирает.
 */
export function syncDraft(draft: DateDraft, server: DateTimeValue): DateDraft {
  if (draft.dirty) return draft
  return sameDateTime(draft.value, server) ? draft : { value: server, dirty: false }
}

export type CommitAction = 'none' | 'commit' | 'revert'

/**
 * Что сделать, когда фокус ушёл из пары полей (или карточку закрыли).
 * `badInput` — браузер держит в поле обрывок (половина даты), а `value` при
 * этом пустое: сохранять такое значит стереть срок, поэтому откатываем.
 */
export function commitAction(
  draft: DateDraft,
  server: DateTimeValue,
  badInput: boolean,
): CommitAction {
  if (!draft.dirty) return 'none'
  if (badInput) return 'revert'
  return sameDateTime(draft.value, server) ? 'none' : 'commit'
}
