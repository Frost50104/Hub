import { describe, expect, it } from 'vitest'

import type { ProductCard } from './learn'
import {
  clampProductFilters,
  DEFAULT_PRODUCT_FILTERS,
  filterProducts,
  filtersShowing,
  normalizeSearch,
  parseProductFilters,
  productFiltersToParams,
  type ProductFilters,
} from './productFilters'

const CAT_HOT = 'c-hot'
const CAT_COLD = 'c-cold'

const card = (over: Partial<ProductCard> = {}): ProductCard => ({
  id: 'p1',
  category_id: CAT_HOT,
  audience_id: null,
  title: 'Латте 250',
  description: null,
  composition: null,
  allergens: null,
  shelf_life: null,
  serving: null,
  upsell: null,
  status: 'published',
  published_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
  photo_urls: [],
  links: [],
  viewed_by_me: false,
  ...over,
})

const filters = (over: Partial<ProductFilters> = {}): ProductFilters => ({
  ...DEFAULT_PRODUCT_FILTERS,
  ...over,
})

describe('parseProductFilters', () => {
  it('пустой адрес — дефолты', () => {
    expect(parseProductFilters(new URLSearchParams())).toEqual(DEFAULT_PRODUCT_FILTERS)
  })

  it('мусор в статусе даёт дефолт, а не пустой экран', () => {
    expect(parseProductFilters(new URLSearchParams('s=zzz')).status).toBe('active')
  })

  it('читает категорию, статус и поиск', () => {
    expect(parseProductFilters(new URLSearchParams(`c=${CAT_HOT}&s=archived&q=латте`))).toEqual({
      category: CAT_HOT,
      status: 'archived',
      q: 'латте',
    })
  })
})

describe('productFiltersToParams', () => {
  it('дефолты в адрес не пишет — /learn/products остаётся канонической ссылкой', () => {
    expect(productFiltersToParams(DEFAULT_PRODUCT_FILTERS).toString()).toBe('')
  })

  it('roundtrip: что записали, то и прочитали', () => {
    const f = filters({ category: CAT_COLD, status: 'draft', q: 'мёд' })
    expect(parseProductFilters(productFiltersToParams(f))).toEqual(f)
  })

  it('сброшенный фильтр вычищает свой ключ из адреса', () => {
    const dirty = productFiltersToParams(filters({ status: 'archived' }))
    expect(productFiltersToParams(DEFAULT_PRODUCT_FILTERS, dirty).toString()).toBe('')
  })
})

describe('clampProductFilters', () => {
  it('сотруднику статусный срез недоступен: чужая ссылка не даёт пустой экран', () => {
    expect(clampProductFilters(filters({ status: 'archived' }), false, [CAT_HOT]).status).toBe(
      'active',
    )
  })

  it('удалённая категория сбрасывается на «Все»', () => {
    expect(clampProductFilters(filters({ category: 'gone' }), true, [CAT_HOT]).category).toBe('all')
  })

  it('пока категории не загружены — выбор не трогаем (иначе затрём ссылку)', () => {
    expect(clampProductFilters(filters({ category: CAT_HOT }), true, []).category).toBe(CAT_HOT)
  })
})

describe('filterProducts', () => {
  const items = [
    card({ id: 'pub', title: 'Латте 250', status: 'published' }),
    card({ id: 'draft', title: 'Раф солёная карамель', status: 'draft' }),
    card({ id: 'review', title: 'Тыквенный латте', status: 'review' }),
    card({ id: 'arch', title: 'Латте старый', status: 'archived' }),
    card({ id: 'cold', title: 'Лимонад', status: 'published', category_id: CAT_COLD }),
  ]
  const ids = (f: ProductFilters) => filterProducts(items, f).map((c) => c.id)

  it('по умолчанию архив скрыт, остальное видно', () => {
    expect(ids(filters())).toEqual(['pub', 'draft', 'review', 'cold'])
  })

  it('«Черновики» включают и «на согласовании»', () => {
    expect(ids(filters({ status: 'draft' }))).toEqual(['draft', 'review'])
  })

  it('«Архив» показывает только архивные', () => {
    expect(ids(filters({ status: 'archived' }))).toEqual(['arch'])
  })

  it('категория и статус работают вместе', () => {
    expect(ids(filters({ category: CAT_COLD }))).toEqual(['cold'])
  })

  it('поиск регистронезависим и не различает ё/е', () => {
    expect(ids(filters({ q: 'ЛАТТЕ' }))).toEqual(['pub', 'review'])
    expect(ids(filters({ q: 'солёная' }))).toEqual(['draft'])
    expect(ids(filters({ q: 'соленая' }))).toEqual(['draft'])
  })

  it('поиск ловит и по названию категории', () => {
    const ctx = { categoryTitle: new Map([[CAT_COLD, 'Холодные напитки']]) }
    expect(filterProducts(items, filters({ q: 'холодные' }), ctx).map((c) => c.id)).toEqual(['cold'])
  })
})

describe('filtersShowing', () => {
  it('показывает категорию и статус созданной карточки', () => {
    const created = card({ id: 'new', category_id: CAT_COLD, status: 'draft' })
    expect(filtersShowing(filters({ category: CAT_HOT, status: 'published' }), created)).toEqual({
      category: CAT_COLD,
      status: 'active',
      q: '',
    })
  })

  it('уже видимую карточку фильтрами не дёргает', () => {
    const saved = card({ status: 'published', category_id: CAT_HOT })
    const current = filters({ category: CAT_HOT, status: 'published', q: 'латте' })
    expect(filtersShowing(current, saved)).toEqual(current)
  })

  it('поиск сбрасывается, только если название под него не подходит', () => {
    const saved = card({ title: 'Эспрессо' })
    expect(filtersShowing(filters({ q: 'латте' }), saved).q).toBe('')
  })

  it('архивную карточку открывает в архиве', () => {
    expect(filtersShowing(filters(), card({ status: 'archived' })).status).toBe('archived')
  })
})

describe('normalizeSearch', () => {
  it('режет пробелы, регистр и ё', () => {
    expect(normalizeSearch('  Мёд  ')).toBe('мед')
  })
})
