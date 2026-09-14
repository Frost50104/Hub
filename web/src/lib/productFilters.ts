import type { ProductCard } from '@/lib/learn'

/**
 * Состояние списка ассортимента: категория, статус, поиск.
 *
 * Живёт в URL, а не в `useState`, по той же причине, что фильтры задач
 * (`lib/taskFilters.ts`): карточка товара — отдельный маршрут, и возврат с неё
 * перемонтирует список. Пока состояние было локальным, человек после каждого
 * захода в карточку оказывался «в начале раздела» — ровно жалоба ОС 09.09.
 *
 * Ключ `p` НЕ занимать: это legacy deep-link карточки (`?p=<id>`), на него
 * ведут поиск и уведомления (`_reindex` пишет `url_path=/learn/products?p=…`).
 */

/** 'active' — всё, кроме архива: чип «Все» архив не показывает (решение владельца). */
export type ProductStatusFilter = 'active' | 'draft' | 'published' | 'archived'

export interface ProductFilters {
  category: string | 'all'
  status: ProductStatusFilter
  q: string
}

export const DEFAULT_PRODUCT_FILTERS: ProductFilters = {
  category: 'all',
  status: 'active',
  q: '',
}

const KEYS = { category: 'c', status: 's', q: 'q' } as const

const STATUSES: ProductStatusFilter[] = ['active', 'draft', 'published', 'archived']

function pickStatus(raw: string | null): ProductStatusFilter {
  // Whitelist, а не приведение типа: `?s=zzz` из чужой ссылки обязан дать
  // дефолтный список, а не пустой экран без объяснения.
  return STATUSES.find((s) => s === raw) ?? DEFAULT_PRODUCT_FILTERS.status
}

export function parseProductFilters(sp: URLSearchParams): ProductFilters {
  return {
    category: sp.get(KEYS.category) || 'all',
    status: pickStatus(sp.get(KEYS.status)),
    q: sp.get(KEYS.q) ?? '',
  }
}

/**
 * Фильтры → параметры. Дефолты НЕ пишутся: `/learn/products` остаётся
 * канонической ссылкой, а «Сбросить фильтры» даёт чистый адрес.
 * `base` сохраняет чужие параметры (их сейчас нет, но ломать их — не наше дело).
 */
export function productFiltersToParams(
  f: ProductFilters,
  base?: URLSearchParams,
): URLSearchParams {
  const next = new URLSearchParams(base)
  const put = (key: string, value: string, dflt: string) => {
    if (value && value !== dflt) next.set(key, value)
    else next.delete(key)
  }
  put(KEYS.category, f.category, 'all')
  put(KEYS.status, f.status, DEFAULT_PRODUCT_FILTERS.status)
  put(KEYS.q, f.q.trim(), '')
  return next
}

/**
 * Привести фильтры к тому, что человек реально может увидеть.
 *
 * ЧИСТАЯ функция: результат нельзя писать обратно в URL. На первом кадре
 * `canManage` ещё false, а категории не загружены — запись затёрла бы `?c=`
 * и `?s=` из прямой ссылки и из возврата с карточки, то есть сломала бы ровно
 * то, ради чего фильтры и переехали в URL.
 */
export function clampProductFilters(
  f: ProductFilters,
  canManage: boolean,
  knownCategoryIds: string[],
): ProductFilters {
  const category =
    f.category === 'all' || knownCategoryIds.length === 0 || knownCategoryIds.includes(f.category)
      ? f.category
      : 'all'
  // Сотруднику сервер отдаёт только опубликованное — статусный срез для него
  // не имеет смысла и чужой ссылкой не должен превращаться в пустой экран.
  return { ...f, category, status: canManage ? f.status : DEFAULT_PRODUCT_FILTERS.status }
}

/** Регистр + ё→е: в меню «мёд» и «мед» — один и тот же товар. */
export function normalizeSearch(s: string): string {
  return s.trim().toLowerCase().replace(/ё/g, 'е')
}

function matchesStatus(card: ProductCard, status: ProductStatusFilter): boolean {
  if (status === 'active') return card.status !== 'archived'
  // «На согласовании» — тоже неопубликованное: иначе такая карточка
  // проваливается между чипами «Черновики» и «Опубликованные».
  if (status === 'draft') return card.status === 'draft' || card.status === 'review'
  return card.status === status
}

export interface ProductMatchContext {
  /** id категории → название: поиск ловит и по названию категории. */
  categoryTitle?: Map<string, string>
}

export function matchesProductFilters(
  card: ProductCard,
  f: ProductFilters,
  ctx: ProductMatchContext = {},
): boolean {
  if (!matchesStatus(card, f.status)) return false
  if (f.category !== 'all' && card.category_id !== f.category) return false
  const q = normalizeSearch(f.q)
  if (!q) return true
  const category = card.category_id ? (ctx.categoryTitle?.get(card.category_id) ?? '') : ''
  return normalizeSearch(card.title).includes(q) || normalizeSearch(category).includes(q)
}

export function filterProducts(
  cards: ProductCard[],
  f: ProductFilters,
  ctx: ProductMatchContext = {},
): ProductCard[] {
  return cards.filter((c) => matchesProductFilters(c, f, ctx))
}

/**
 * Минимальная правка фильтров, чтобы только что сохранённая карточка была на
 * экране: категорию в форме меняют, статус мог не совпасть с чипом, а поиск —
 * с названием. Без этого «Сохранить» снова выглядит как «ничего не произошло»:
 * плитки нет, подсвечивать нечего.
 */
export function filtersShowing(current: ProductFilters, card: ProductCard): ProductFilters {
  const next: ProductFilters = {
    category: card.category_id ?? 'all',
    status: matchesStatus(card, current.status) ? current.status : 'active',
    q: normalizeSearch(card.title).includes(normalizeSearch(current.q)) ? current.q : '',
  }
  // Архивную карточку «активный» срез не покажет — честнее открыть архив.
  if (card.status === 'archived') next.status = 'archived'
  return next
}
