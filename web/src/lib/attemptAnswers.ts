/**
 * Человекочитаемый текст ответа в разборе попытки (админский отчёт аттестаций).
 *
 * Всё считается ОТ СНАПШОТА попытки: варианты шаффлятся per attempt, а
 * правильный ответ переиндексирован под предъявленный порядок
 * (`quiz_scoring.build_snapshot`) — тексты из текущих QuizQuestion сюда
 * подставлять нельзя, после правки/реимпорта они другие.
 *
 * Формы значений (источник истины — `quiz_scoring._is_correct`):
 * single — int-индекс; multi — int[]; match — список right-индексов по
 * позициям left; order — список предъявленных индексов в выбранном порядке;
 * open — строка. Ничего из этого не гарантировано (старые снапшоты,
 * пропуски) — на мусоре не падаем, отвечаем прочерком.
 *
 * Чистые функции ради vitest: jsdom в проекте нет.
 */

import type { QuizSnapshotQuestion } from '@/lib/learn'

export const NO_ANSWER = 'Без ответа'

function optionText(list: string[] | undefined, index: unknown): string {
  if (typeof index !== 'number' || !Number.isInteger(index)) return '—'
  return list?.[index] ?? '—'
}

function isIndexList(value: unknown): value is number[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'number')
}

/** Ответ сотрудника; пустой/недоотвеченный → «Без ответа». */
export function describeAnswer(q: QuizSnapshotQuestion, value: unknown): string {
  if (value === null || value === undefined) return NO_ANSWER
  switch (q.qtype) {
    case 'single':
      return optionText(q.options.options, value)
    case 'multi': {
      if (!isIndexList(value) || value.length === 0) return NO_ANSWER
      return value.map((i) => optionText(q.options.options, i)).join('; ')
    }
    case 'match': {
      if (!isIndexList(value) || value.length === 0) return NO_ANSWER
      const left = q.options.left ?? []
      return value
        .map((rightIdx, i) => `${left[i] ?? '—'} → ${optionText(q.options.right, rightIdx)}`)
        .join('; ')
    }
    case 'order': {
      if (!isIndexList(value) || value.length === 0) return NO_ANSWER
      return value.map((i) => optionText(q.options.items, i)).join(' → ')
    }
    case 'open':
      return typeof value === 'string' && value.trim() ? value : NO_ANSWER
    default:
      return typeof value === 'string' ? value : '—'
  }
}

/** Правильный ответ из `correct_answers` снапшота (ключи — как в answer). */
export function describeCorrect(
  q: QuizSnapshotQuestion,
  answer: Record<string, unknown> | undefined,
): string {
  if (!answer) return '—'
  switch (q.qtype) {
    case 'single':
    case 'multi': {
      const correct = answer.correct
      if (!isIndexList(correct) || correct.length === 0) return '—'
      return correct.map((i) => optionText(q.options.options, i)).join('; ')
    }
    case 'match': {
      const pairs = answer.pairs
      if (!Array.isArray(pairs) || pairs.length === 0) return '—'
      const left = q.options.left ?? []
      return pairs
        .map((pair) => {
          if (!isIndexList(pair) || pair.length !== 2) return '—'
          const [leftIdx, rightIdx] = pair
          return `${left[leftIdx!] ?? '—'} → ${optionText(q.options.right, rightIdx)}`
        })
        .join('; ')
    }
    case 'order': {
      const order = answer.order
      if (!isIndexList(order) || order.length === 0) return '—'
      return order.map((i) => optionText(q.options.items, i)).join(' → ')
    }
    default:
      // open проверяет человек — «правильного варианта» нет.
      return '—'
  }
}
