/**
 * Фильтрация вариантов выпадающего списка — БЕЗ React и DOM.
 *
 * Отдельным модулем по той же причине, что `peopleOptions.ts` и `taskContext.ts`:
 * vitest здесь бежит без jsdom, компонент не покрыть, а правило поиска покрыть
 * обязано — именно в нём прячется самая дорогая ошибка (см. `queryTokens`).
 *
 * Правила зеркалят серверный `app/services/people_search.py`. Это не
 * педантизм: справочник ФИО записан в СМЕШАННОМ порядке (на проде 139 человек
 * «Имя Фамилия» и 70 «Фамилия Имя»), и подстрочный `includes` находил бы
 * 0 из 225 двухсловных имён при обратном порядке слов — замер 14.09, ровно тот
 * баг, из-за которого переписывали поиск по упоминаниям.
 */

export interface SelectOption {
  value: string
  label: string
  /** Вторая строка пункта: почта, счётчик, ключ проекта. Ищется наравне с label. */
  meta?: string
}

/** Зеркало `people_search.MAX_TOKENS`: больше четырёх слов в запрос не берём. */
const MAX_TOKENS = 4

/** `ё → е` и нижний регистр — как `people_search.normalize`. */
export function normalize(value: string): string {
  return value.toLowerCase().replace(/ё/g, 'е').trim()
}

/** Запрос → слова. Пустой запрос даёт пустой список, то есть «не фильтруем». */
export function queryTokens(query: string): string[] {
  return normalize(query).split(/\s+/).filter(Boolean).slice(0, MAX_TOKENS)
}

/**
 * Совпадение: КАЖДОЕ слово запроса найдено в `label` ИЛИ в `meta`.
 *
 * AND между словами и OR между полями — то же, что делает `match_condition` на
 * сервере. Порядок слов при этом не важен: «Попов Пётр» находит «Пётр Попов».
 */
export function optionMatches(option: SelectOption, tokens: readonly string[]): boolean {
  if (tokens.length === 0) return true
  const haystack = normalize(`${option.label} ${option.meta ?? ''}`)
  return tokens.every((token) => haystack.includes(token))
}

/**
 * Отфильтровать — и отдать ВСЁ, что подошло.
 *
 * Потолка выдачи здесь нет и быть не должно (решение владельца 16.09, после
 * живого бага). Сначала я обрезал список до 50 строк «ради экономии узлов
 * DOM» — и это молча спрятало 84% справочника: «Пётр Попов» стоит 246-м из 313
 * по алфавиту, то есть в списке руководителей его просто не было. Нативный
 * `<select>`, который мы заменяли, показывал всех и прокручивался. Экономия,
 * из-за которой человека нельзя выбрать, — не экономия.
 */
export function filterOptions(
  options: readonly SelectOption[],
  query: string,
): SelectOption[] {
  const tokens = queryTokens(query)
  return options.filter((o) => optionMatches(o, tokens))
}

/**
 * Подпись выбранного значения.
 *
 * `fallback` — не перестраховка. Форма карточки сотрудника отсеивает архивные
 * магазины и показывает только активные карточки, а выбранным может остаться
 * именно архивный: нативный `<select>` в этом случае рисует пустоту, и это
 * терпели, но у кнопки-триггера пустота читается как «поле не заполнено» —
 * человек перезапишет чужое значение, не заметив. Тот же проп по той же
 * причине есть у `PeoplePicker` (`currentLabel`).
 */
export function selectedLabel(
  options: readonly SelectOption[],
  value: string | null,
  fallback?: string | null,
): string | null {
  if (!value) return null
  return options.find((o) => o.value === value)?.label ?? fallback ?? null
}
