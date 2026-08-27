/**
 * Блок «Контрольный вопрос» урока — сборка атрибутов для вставки и правки.
 *
 * Чистая по двум причинам. Первая: vitest здесь без jsdom, и логика внутри
 * компонента тестами не покрывается вовсе. Вторая: два правила ниже стоят
 * дорого, и оба невидимы на экране до того, как навредят.
 */

export interface CheckQuestionDraft {
  question: string
  /** Как в форме — с возможными пустыми строками. */
  options: string[]
  /** Индекс правильного В ИСХОДНОМ массиве формы. */
  correct: number
  gateNext: boolean
}

export interface CheckQuestionAttrs {
  blockId: string
  question: string
  options: string[]
  correct: number
  gateNext: boolean
}

/** Зеркало серверных границ (`app/services/lesson_content.py::_validate_extra_node`). */
export const MIN_OPTIONS = 2
export const MAX_OPTIONS = 10

/**
 * `null` — форму отправлять нельзя (кнопка блокируется).
 *
 * `existingBlockId` передаётся при ПРАВКЕ и не заменяется новым: `blockId` —
 * ключ, по которому сервер хранит ответы сотрудников и считает гейт завершения
 * урока (`check_answer`, `collect_gate_blocks`). Новый id означает «вопрос, на
 * который никто не отвечал»: гейт снова потребует ответа у тех, кто урок ещё не
 * закрыл, а прежние ответы останутся мусором в `block_state`.
 */
export function buildCheckAttrs(
  draft: CheckQuestionDraft,
  existingBlockId?: string | null,
): CheckQuestionAttrs | null {
  const question = draft.question.trim()
  if (!question) return null

  // Пустые варианты выбрасываются ВМЕСТЕ с пересчётом индекса правильного:
  // раньше `correct` считался по неотфильтрованному массиву, и стоило удалить
  // вариант выше правильного — верным молча становился соседний ответ.
  const kept = draft.options
    .map((option, index) => ({ option: option.trim(), index }))
    .filter((o) => o.option.length > 0)
  if (kept.length < MIN_OPTIONS || kept.length > MAX_OPTIONS) return null

  const correct = kept.findIndex((o) => o.index === draft.correct)
  // Правильный вариант стёрли — сохранять нечего: сервер ответит 422, а на
  // экране это выглядело бы как «сохранилось, но ответ не тот».
  if (correct === -1) return null

  return {
    blockId: existingBlockId || crypto.randomUUID(),
    question,
    options: kept.map((o) => o.option),
    correct,
    gateNext: draft.gateNext,
  }
}
