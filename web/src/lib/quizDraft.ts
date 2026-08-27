/**
 * «Изменился ли черновик теста» — чтобы закрытие диалога не выбрасывало работу
 * молча.
 *
 * Инцидент 26.08 (`docs/tech-debt/incidents.md`): вопросы аттестации живут в
 * состоянии вкладки до нажатия «Сохранить». Пересев по рефетчу починен, но
 * «Отмена», крестик, Escape и клик мимо диалога по-прежнему выбрасывают набор
 * без единого слова. Сравнение вынесено сюда, а не написано тернарником в
 * разметке: `options` и `answer` — произвольный JSON, и наивное сравнение
 * ссылок или `JSON.stringify` с разным порядком ключей врало бы в обе стороны.
 */

import { type QuizManage, type QuizQuestionDraft } from '@/lib/learn'

/**
 * Стабильная строка из произвольного JSON: ключи объектов сортируются.
 *
 * Порядок ключей в `answer` не совпадает между тем, что пришло с сервера
 * (JSON.parse сохраняет порядок ответа) и тем, что собрал редактор вопроса.
 * Без сортировки диалог спрашивал бы «точно закрыть?» там, где не изменилось
 * ничего, и люди привыкли бы отвечать «да» не глядя.
 */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'null'
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonicalJson(v)}`).join(',')}}`
}

/** Один вопрос целиком, включая варианты и правильный ответ. */
export function sameQuestion(a: QuizQuestionDraft, b: QuizQuestionDraft): boolean {
  return (
    a.qtype === b.qtype &&
    a.prompt === b.prompt &&
    a.points === b.points &&
    // `undefined` и `null` у media_id означают одно и то же — «картинки нет».
    (a.media_id ?? null) === (b.media_id ?? null) &&
    canonicalJson(a.options) === canonicalJson(b.options) &&
    canonicalJson(a.answer ?? null) === canonicalJson(b.answer ?? null)
  )
}

export interface QuizDraftSnapshot {
  passScore: number
  /** Строка, а не число: пустая означает «без лимита». */
  attemptsLimit: string
  questions: QuizQuestionDraft[]
}

/** Отличается ли черновик от того, с чего человек начал. */
export function quizDraftDirty(
  current: QuizDraftSnapshot,
  seeded: QuizDraftSnapshot | null,
): boolean {
  // Пока не засеяли — сравнивать не с чем, и спрашивать не о чем.
  if (!seeded) return false
  if (current.passScore !== seeded.passScore) return true
  if (current.attemptsLimit.trim() !== seeded.attemptsLimit.trim()) return true
  if (current.questions.length !== seeded.questions.length) return true
  return current.questions.some((q, i) => {
    const was = seeded.questions[i]
    return !was || !sameQuestion(q, was)
  })
}

/**
 * Серверный набор → черновик редактора.
 *
 * Функция ОДНА на два вызова — первичный сев и пересев после импорта вопросов.
 * Разъехаться им нельзя: если пересев после импорта не обновит снимок
 * `seededRef`, диалог начнёт спрашивать «выйти без сохранения?» на ровном
 * месте, и к вопросу привыкнут жать «да», теряя настоящие правки.
 *
 * `attempts_limit: null` («без лимита») превращается в ПУСТУЮ строку, а не в
 * `'0'`: поле ввода строковое, и ноль означал бы «ни одной попытки».
 */
export function quizSnapshot(data: QuizManage): QuizDraftSnapshot {
  return {
    passScore: data.pass_score_pct,
    attemptsLimit: data.attempts_limit === null ? '' : String(data.attempts_limit),
    questions: data.questions.map((q) => ({
      qtype: q.qtype,
      prompt: q.prompt,
      media_id: q.media_id,
      options: q.options,
      answer: q.answer,
      points: q.points,
    })),
  }
}

/**
 * Правка ОДНОГО вопроса сравнивается по СЫРЫМ полям формы, а не по собранному
 * черновику: пока форма невалидна (пустой текст, один вариант), черновик не
 * собирается вовсе — сравнивать было бы нечего. Заодно случай «открыл новый
 * вопрос и передумал» решается сам: пустая форма совпадает со своим снимком.
 *
 *     const snapshot = canonicalJson({ qtype, prompt, points, options, ... })
 *
 * Один текст на все места, где закрытие выбрасывает работу.
 */
export const DISCARD_QUIZ_CONFIRM =
  'Изменения не сохранены — они пропадут. Закрыть без сохранения?'
