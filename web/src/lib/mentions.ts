/**
 * Упоминания через «@»: разбор ввода, вставка и показ.
 *
 * ОС 14.09: «невозможно написать через @ имя и фамилию, Хаб не находит
 * человека в справочнике, приходится смотреть логин в почте». Причина была
 * прямо здесь: сегмент после «@» считался по классу `[A-Za-z0-9._-]`, и первая
 * же русская буква закрывала попап — запрос на сервер не уходил вовсе.
 *
 * Правила живут в чистых функциях, потому что vitest в проекте без jsdom:
 * компонент не протестировать, а разбор ввода — можно и нужно.
 *
 * ЗЕРКАЛО СЕРВЕРА. Грамматика токена совпадает с `app/services/mention_parser.py`
 * и `app/services/public_token.py` — меняется только тройкой, иначе комментарий
 * будет резолвиться, но рисоваться без чипа (или наоборот).
 */

/** Символы тела токена: буквы любого алфавита, цифры, `_`, `.`, `-`. */
const TOKEN_CHAR = /[\p{L}\p{N}._-]/u
/** Готовый токен в тексте — для подсветки при рендере. */
export const MENTION_TOKEN_RE = /(@[\p{L}\p{N}._-]+)/gu
/** Символ перед «@» не должен быть частью слова: `ivan@host.ru` — не упоминание. */
const WORD_CHAR = /[\p{L}\p{N}_]/u

/**
 * Длиннее этого искать бессмысленно: иначе попап живёт до конца абзаца,
 * перехватывая Enter у человека, который давно пишет обычный текст.
 */
export const MAX_QUERY_LEN = 40

export interface MentionContext {
  /** Индекс самого «@» в тексте. */
  anchor: number
  /** Что набрано после «@» — уходит в поиск как есть. */
  query: string
}

/**
 * Где сейчас каретка: внутри набираемого упоминания или нет.
 *
 * Отличия от прежней версии, каждое — из разбора жалобы:
 * - класс символов юникодный (кириллица больше не закрывает попап);
 * - разрешён РОВНО ОДИН пробел — чтобы искать «Иван Петров», а не только
 *   первое слово. Два пробела подряд, перевод строки и второй «@» сегмент
 *   обрывают;
 * - пробел сразу после «@» не считается: «Стоимость 5 @ 10 руб» попап не
 *   открывает;
 * - граница перед «@» проверяется юникодно (раньше JS-ный `\w` = ASCII, и
 *   «Привет@ivan» фронт считал упоминанием, а бэкенд — нет).
 */
export function mentionContext(text: string, cursor: number): MentionContext | null {
  let i = cursor - 1
  let spaces = 0
  while (i >= 0) {
    const ch = text[i]!
    if (TOKEN_CHAR.test(ch)) {
      i -= 1
      continue
    }
    if (ch === ' ') {
      // Пробел допустим один и только между словами: слева от него обязана
      // быть часть токена, а не сам «@».
      const prev = text[i - 1]
      if (spaces > 0 || prev === undefined || !TOKEN_CHAR.test(prev)) return null
      spaces += 1
      i -= 1
      continue
    }
    break
  }
  if (i < 0 || text[i] !== '@') return null
  const before = text[i - 1]
  if (before !== undefined && WORD_CHAR.test(before)) return null
  const query = text.slice(i + 1, cursor)
  if (query.length > MAX_QUERY_LEN) return null
  return { anchor: i, query }
}

/** Заменить набранный сегмент готовым токеном с сервера. */
export function applyMention(
  text: string,
  anchor: number,
  cursor: number,
  token: string,
): { next: string; caret: number } {
  const inserted = `@${token} `
  const next = text.slice(0, anchor) + inserted + text.slice(cursor)
  return { next, caret: anchor + inserted.length }
}

/** Канонический вид токена для поиска в словаре имён (зеркало `normalize_token`). */
export function normalizeToken(raw: string): string {
  return raw.trim().toLowerCase().replace(/ё/g, 'е').replace(/[.-]+$/, '')
}

/**
 * Разбор токена на чип и хвост.
 *
 * `chip` — то, что подсвечивается: текущее ФИО с сервера, а для неизвестного
 * токена (человека удалили, комментарий пришёл со старого бандла) сам токен
 * без подчёркиваний — «@Иван Петров» читается, «@Иван_Петров» выглядит
 * поломкой. `tail` — хвостовая пунктуация: «.» и «-» нужны внутри логинов, но
 * точка в конце предложения не должна ни пропадать, ни попадать в подсветку.
 */
export function mentionParts(
  part: string,
  names?: Record<string, string>,
): { chip: string; tail: string } {
  const raw = part.slice(1)
  const core = raw.replace(/[.-]+$/, '')
  const tail = raw.slice(core.length)
  const name = names?.[normalizeToken(raw)]
  return { chip: `@${name ?? core.replace(/_/g, ' ')}`, tail }
}

/** Готовая строка «@Имя Фамилия» с хвостом — для мест без разметки. */
export function mentionDisplay(part: string, names?: Record<string, string>): string {
  const { chip, tail } = mentionParts(part, names)
  return chip + tail
}
