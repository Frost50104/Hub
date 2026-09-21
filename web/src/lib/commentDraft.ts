/**
 * Длина комментария задачи: потолок и подсказка под полем (ОС 21.09 — отчёт на
 * 9 279 символов не уходил, а человек видел «Request failed with status code 422»).
 *
 * `COMMENT_MAX_LENGTH` — зеркало `app/schemas/comment.py::COMMENT_MAX_LENGTH`,
 * меняются ПАРОЙ (CLAUDE.md, «Зеркала»). Разойдутся — сервер снова ответит 422
 * на то, что клиент пустил; текст ошибки после этого хотя бы читаемый
 * (`lib/errors.ts`).
 *
 * `maxLength` на поле намеренно НЕ ставится: при вставке браузер молча режет
 * текст до лимита, и длинный отчёт ушёл бы без хвоста без единого сообщения.
 * Вместо этого — счётчик у края лимита и блокировка отправки сверх него.
 */

import { NBSP } from '@/lib/typography'

export const COMMENT_MAX_LENGTH = 20_000

/**
 * С какой длины показываем счётчик — 90 % лимита. У обычных комментариев
 * (на проде p99 ≈ 935 символов) подсказка не появляется вовсе.
 */
export const COMMENT_HINT_FROM = Math.floor(COMMENT_MAX_LENGTH * 0.9)

export interface CommentLengthHint {
  show: boolean
  over: boolean
  text: string
}

/**
 * Длина в символах так, как её считает сервер: pydantic меряет строку Python —
 * кодовыми точками, а `String.length` в JS — UTF-16-единицами, и эмодзи дал
 * бы два вместо одного. Считаем то, что реально уйдёт, — обрезанный текст.
 */
export function commentLength(text: string): number {
  // Итератор строки идёт по кодовым точкам — ровно как len() в Python.
  return Array.from(text.trim()).length
}

const fmt = (n: number): string => n.toLocaleString('ru-RU').replace(/\s/g, NBSP)

export function commentLengthHint(text: string): CommentLengthHint {
  const length = commentLength(text)
  if (length > COMMENT_MAX_LENGTH) {
    return {
      show: true,
      over: true,
      text: `Длиннее ${fmt(COMMENT_MAX_LENGTH)} символов (сейчас ${fmt(length)}) — сократите или разбейте на несколько комментариев`,
    }
  }
  if (length >= COMMENT_HINT_FROM) {
    return { show: true, over: false, text: `${fmt(length)} / ${fmt(COMMENT_MAX_LENGTH)}` }
  }
  return { show: false, over: false, text: '' }
}
