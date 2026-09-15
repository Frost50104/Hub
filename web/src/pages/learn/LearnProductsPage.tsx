import { useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  ArrowLeft,
  BookOpen,
  FolderCog,
  ImagePlus,
  Pencil,
  Plus,
  Search,
  Send,
  ShoppingBag,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AudiencePicker, useAudienceDraft } from '@/components/learn/AudiencePicker'
import { FavoriteStar } from '@/components/learn/FavoriteStar'
import { QueryError } from '@/components/QueryError'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { FilterChip } from '@/components/ui/FilterChip'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SearchableSelect } from '@/components/ui/SearchableSelect'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useCourses, useProductMutation, useProducts } from '@/hooks/useLearn'
import { audienceDraftProblem } from '@/lib/audienceHints'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import {
  CONTENT_STATUS_LABEL,
  learnApi,
  type ProductCard,
  type ProductCategory,
  type ProductUpsert,
} from '@/lib/learn'
import {
  clampProductFilters,
  DEFAULT_PRODUCT_FILTERS,
  filterProducts,
  filtersShowing,
  matchesProductFilters,
  parseProductFilters,
  productFiltersToParams,
  type ProductFilters,
  type ProductStatusFilter,
} from '@/lib/productFilters'
import {
  canEditProductAudience,
  canPublishProduct,
  canSaveProduct,
  productStatusActions,
} from '@/lib/productForm'
import { nbsp, plural } from '@/lib/typography'

/**
 * Ассортимент (Ф4, ТЗ §9) по макету «Урок — редизайн» (route products):
 * сетка плиток с фото 104/132 (или пустой слот на `--surface`: у ранней
 * эксплуатации фото загружены не везде), чипы категорий `FilterChip`, счётчик
 * «N из M позиций», карточка позиции — ОТДЕЛЬНЫЙ маршрут `/learn/products/:id`
 * (раньше — диалог): на телефоне фото 200 → H1 → `<dl>` → «Что предложить
 * вместе» → «Изучить по теме», на десктопе двухколонник 300 | 1fr — состав и
 * аллергены читают рядом с плиткой, а не поверх списка. Бейдж «новинка для
 * вас» снят: `viewed_by_me` — служебный факт, не маркетинговая новинка.
 * Открытие карточки фиксируется (view_history + балл рейтинга за первое
 * знакомство) — один раз, сервером.
 */

/** Ряд действий: 48px на телефоне, 36px на десктопе. */
const ACTION_BTN =
  'h-12 rounded-xl px-5 text-[15px] lg:h-9 lg:rounded-[10px] lg:px-3.5 lg:text-[13px]'
const GHOST_BTN = cn(ACTION_BTN, 'bg-transparent')

function useProductsData() {
  const probe = useProducts(false)
  const canManage =
    probe.data !== undefined && ['admin', 'publisher', 'author'].includes(probe.data.content_role)
  const managed = useProducts(true, canManage)
  const data = canManage ? (managed.data ?? probe.data) : probe.data
  return { probe, canManage, data }
}

function PhotoPlaceholder({ className, iconClass }: { className: string; iconClass: string }) {
  return (
    <span className={cn('flex items-center justify-center bg-surface text-text2', className)}>
      <ShoppingBag className={iconClass} strokeWidth={1.7} />
    </span>
  )
}

// ─── Список ──────────────────────────────────────────────────────────────────

const STATUS_CHIPS: { value: ProductStatusFilter; label: string; title: string }[] = [
  { value: 'active', label: 'Все', title: 'Все, кроме архива' },
  { value: 'draft', label: 'Черновики', title: 'Черновики и карточки на согласовании' },
  { value: 'published', label: 'Опубликованные', title: 'Видны сотрудникам' },
  { value: 'archived', label: 'Архив', title: 'Сняты с публикации' },
]

export function LearnProductsPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [editorCard, setEditorCard] = useState<ProductCard | 'new' | null>(null)
  const [categoriesOpen, setCategoriesOpen] = useState(false)
  // Только что сохранённая карточка: к ней скроллим и её обводим.
  const [focusId, setFocusId] = useState<string | null>(null)
  const { probe, canManage, data } = useProductsData()

  const all = useMemo(() => data?.items ?? [], [data])
  const categories = useMemo(() => data?.categories ?? [], [data])
  const categoryTitle = useMemo(
    () => new Map(categories.map((c) => [c.id, c.title])),
    [categories],
  )
  // clamp только ВЫЧИСЛЯЕТ: записать его результат в адрес нельзя — на первом
  // кадре нет ни categories, ни canManage, и ссылка вида `?c=…&s=archived`
  // (возврат с карточки, чужая ссылка) была бы затёрта до загрузки данных.
  const filters = useMemo(
    () => clampProductFilters(parseProductFilters(params), canManage, categories.map((c) => c.id)),
    [params, canManage, categories],
  )
  const setFilters = useCallback(
    (next: ProductFilters) => setParams(productFiltersToParams(next, params), { replace: true }),
    [params, setParams],
  )
  const items = useMemo(
    () => filterProducts(all, filters, { categoryTitle }),
    [all, filters, categoryTitle],
  )
  // Знаменатель — по текущему статусному срезу: со скрытым архивом «5 из 131»
  // читалось бы как потеря карточек.
  const total = useMemo(
    () =>
      all.filter((c) =>
        matchesProductFilters(c, { ...filters, category: 'all', q: '' }, { categoryTitle }),
      ).length,
    [all, filters, categoryTitle],
  )
  // Поиск нашёл бы это в архиве, но архив скрыт — говорим об этом вслух,
  // иначе прячущийся архив породит новую версию жалобы «товар не находится».
  const archivedHits = useMemo(
    () =>
      filters.status === 'archived' || !filters.q.trim()
        ? 0
        : filterProducts(all, { ...filters, status: 'archived' }, { categoryTitle }).length,
    [all, filters, categoryTitle],
  )
  const filtersActive =
    filters.category !== 'all' ||
    filters.status !== DEFAULT_PRODUCT_FILTERS.status ||
    filters.q.trim() !== ''

  // Скролл к сохранённой карточке — callback-ref: узел появится только после
  // рефетча списка, и ловить его таймером или querySelector'ом незачем.
  // rAF обязателен: Radix при закрытии диалога возвращает фокус на «+ Товар»
  // (layout-эффект размонтирования), и браузер скроллит к кнопке.
  const focusTile = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    requestAnimationFrame(() => node.scrollIntoView({ block: 'center', behavior: 'smooth' }))
  }, [])

  useEffect(() => {
    if (!focusId) return undefined
    const timer = setTimeout(() => setFocusId(null), 2500)
    return () => clearTimeout(timer)
  }, [focusId])

  const onSaved = useCallback(
    (card: ProductCard) => {
      // Сначала показать место, где карточка реально лежит: категорию меняют
      // прямо в форме, а статус мог не совпасть с активным чипом.
      setFilters(filtersShowing(filters, card))
      setFocusId(card.id)
    },
    [filters, setFilters],
  )

  // Старый deep-link `?p=` (поиск, уведомления) → маршрут карточки.
  // ВНИМАНИЕ: ранний return. Любой новый хук — ТОЛЬКО выше этой строки.
  const legacy = params.get('p')
  if (legacy) return <Navigate to={`/learn/products/${legacy}`} replace />

  const counter = data ? nbsp(`${items.length} из ${plural(total, 'позиции', 'позиций', 'позиций')}`) : ''

  const open = (card: ProductCard) => {
    if (card.status === 'published') void learnApi.openProduct(card.id)
    // Фильтры едут с собой: возврат «Ассортимент» вернёт в тот же срез.
    navigate({ pathname: `/learn/products/${card.id}`, search: params.toString() })
  }

  return (
    <div className="mx-auto max-w-[920px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
      <header className="flex flex-col gap-3.5 lg:flex-row lg:flex-wrap lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="mb-1 min-h-[1em] text-[12px] leading-[1.35] text-text2 lg:hidden">{counter}</p>
          <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
            Ассортимент
          </h1>
          <p className="mt-2.5 hidden text-[18px] leading-[1.6] text-text2 lg:block">
            {counter && `${counter}. `}
            Позиция засчитывается в рейтинг один раз — за первое открытие.
          </p>
        </div>
        {canManage && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setEditorCard('new')} className={cn(ACTION_BTN, 'order-first lg:order-last')}>
              <Plus className="h-4 w-4" /> Товар
            </Button>
            <Button variant="secondary" className={GHOST_BTN} onClick={() => setCategoriesOpen(true)}>
              <FolderCog className="h-4 w-4" /> Категории
            </Button>
          </div>
        )}
      </header>

      {/* Поле 48px, input растянут на всю высоту строки: иначе фокус ловит 23px. */}
      <div className="mt-4 lg:mt-[22px]">
        <div className="flex min-h-[48px] items-center gap-2.5 rounded-xl border border-glass-border bg-tint px-3.5">
          <Search className="h-[18px] w-[18px] shrink-0 text-text2" />
          <input
            type="text"
            value={filters.q}
            onChange={(e) => setFilters({ ...filters, q: e.target.value })}
            placeholder="Название или категория"
            aria-label="Поиск по ассортименту"
            className="min-w-0 flex-1 self-stretch border-none bg-transparent text-[16px] text-text outline-none placeholder:text-text2"
          />
          {filters.q && (
            <button
              type="button"
              onClick={() => setFilters({ ...filters, q: '' })}
              aria-label="Очистить"
              className="-mr-2.5 flex h-11 w-11 shrink-0 items-center justify-center text-text2 hover:text-text"
            >
              <X className="h-[18px] w-[18px]" />
            </button>
          )}
        </div>
      </div>

      {/* Статусы — только тем, кто ведёт контент: сотруднику сервер отдаёт
          только опубликованное, и чип «Черновики» был бы вечной пустотой. */}
      {canManage && (
        <div
          role="group"
          aria-label="Статус"
          className="-mx-5 mt-3 flex gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none] lg:mx-0 lg:flex-wrap lg:px-0"
        >
          {STATUS_CHIPS.map((chip) => (
            <FilterChip
              key={chip.value}
              active={filters.status === chip.value}
              title={chip.title}
              onClick={() => setFilters({ ...filters, status: chip.value })}
            >
              {chip.label}
            </FilterChip>
          ))}
        </div>
      )}

      {categories.length > 0 && (
        <div
          role="group"
          aria-label="Категория"
          className="-mx-5 mt-3 flex gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none] lg:mx-0 lg:flex-wrap lg:px-0"
        >
          <FilterChip
            active={filters.category === 'all'}
            onClick={() => setFilters({ ...filters, category: 'all' })}
          >
            Все категории
          </FilterChip>
          {categories.map((c) => (
            <FilterChip
              key={c.id}
              active={filters.category === c.id}
              onClick={() => setFilters({ ...filters, category: c.id })}
            >
              {c.title}
            </FilterChip>
          ))}
        </div>
      )}

      <div className="mt-3.5 lg:mt-[22px]">
        {probe.isLoading && <SkeletonRows rows={4} />}
        {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}
        {data && items.length === 0 && (
          <EmptyState
            layout="card"
            icon={<ShoppingBag className="h-7 w-7" />}
            title={filtersActive ? 'Ничего не нашлось' : 'Карточек пока нет'}
            text={
              filtersActive
                ? archivedHits > 0
                  ? `Под этот запрос ничего нет, но в архиве есть ${plural(archivedHits, 'совпадение', 'совпадения', 'совпадений')}.`
                  : 'Попробуйте другой запрос или снимите фильтры.'
                : canManage
                  ? 'Заведите позицию: состав, аллергены, срок, подача и фото — сотрудники откроют её у стойки.'
                  : 'Позиции ассортимента появятся здесь, как только их опубликуют.'
            }
            cta={canManage ? 'Новый товар' : undefined}
            onCta={canManage ? () => setEditorCard('new') : undefined}
            secondaryCta={
              archivedHits > 0 ? 'Искать в архиве' : filtersActive ? 'Сбросить фильтры' : undefined
            }
            onSecondary={
              archivedHits > 0
                ? () => setFilters({ ...filters, status: 'archived' })
                : filtersActive
                  ? () => setFilters(DEFAULT_PRODUCT_FILTERS)
                  : undefined
            }
          />
        )}
        {items.length > 0 && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 lg:gap-3.5">
            {items.map((card) => (
              // Обёртка держит рамку и фон, кнопка — только зону открытия:
              // звезда это кнопка, а вложенная кнопка невалидна.
              <div
                key={card.id}
                ref={card.id === focusId ? focusTile : undefined}
                className={cn(
                  'relative flex flex-col overflow-hidden rounded-[14px] border border-hair bg-tint transition-colors hover:border-amber/50',
                  // Кольцо рисуется снаружи элемента, собственный overflow-hidden
                  // его не режет (клипуются только дети).
                  card.id === focusId && 'ring-2 ring-amber ring-offset-2 ring-offset-bg',
                )}
              >
                <button
                  type="button"
                  onClick={() => open(card)}
                  className="flex flex-1 flex-col text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                >
                  {card.photo_urls[0] ? (
                    <img
                      src={card.photo_urls[0]}
                      alt={card.title}
                      loading="lazy"
                      className="h-[104px] w-full object-cover lg:h-[132px]"
                    />
                  ) : (
                    <PhotoPlaceholder className="h-[104px] w-full lg:h-[132px]" iconClass="h-[26px] w-[26px] lg:h-[30px] lg:w-[30px]" />
                  )}
                  <span className="flex flex-col gap-1.5 px-3 pb-[13px] pt-[11px] lg:px-[13px] lg:pb-3.5 lg:pt-3">
                    <span className="text-[16px] font-semibold leading-[1.3] text-text lg:text-[17px]">{card.title}</span>
                    {card.status !== 'published' && (
                      <Badge variant="outline" className="self-start">
                        {CONTENT_STATUS_LABEL[card.status]}
                      </Badge>
                    )}
                  </span>
                </button>
                {/* Подложка обязательна: звезда лежит поверх фото товара, и на
                    светлом снимке амбер по амберу не читался бы. */}
                <FavoriteStar
                  objectType="product"
                  objectId={card.id}
                  title={card.title}
                  className="absolute right-1.5 top-1.5 h-8 w-8 bg-bg/70 backdrop-blur-sm"
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {editorCard !== null && (
        <ProductEditorDialog
          initial={editorCard === 'new' ? null : editorCard}
          categories={categories}
          defaultCategoryId={filters.category === 'all' ? '' : filters.category}
          role={data?.content_role ?? 'none'}
          onSaved={onSaved}
          onClose={() => setEditorCard(null)}
        />
      )}
      {categoriesOpen && (
        // Сбрасывать фильтр вслепую нельзя: диалог закрывают и просто так.
        // Удалённую категорию снимет clampProductFilters после рефетча.
        <CategoriesDialog categories={categories} onClose={() => setCategoriesOpen(false)} />
      )}
    </div>
  )
}

// ─── Карточка позиции: отдельный маршрут ─────────────────────────────────────

export function LearnProductPage() {
  const { productId = '' } = useParams()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { probe, canManage, data } = useProductsData()
  const [photoIdx, setPhotoIdx] = useState(0)
  const [editing, setEditing] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const setStatus = useProductMutation((status: 'published' | 'archived') =>
    learnApi.setProductStatus(productId, status),
  )

  const card = data?.items.find((i) => i.id === productId) ?? null
  const role = data?.content_role ?? 'none'
  // `replace`, а не push: иначе системная «Назад» возвращала бы на только что
  // покинутую карточку. Фильтры списка приехали в адресе — возвращаем их.
  const back = () =>
    navigate({ pathname: '/learn/products', search: params.toString() }, { replace: true })

  const fields = card
    ? ([
        ['Состав', card.composition],
        ['Аллергены', card.allergens],
        ['Срок годности', card.shelf_life],
        ['Подача', card.serving],
      ] as const).filter(([, v]) => Boolean(v))
    : []

  const photo = card?.photo_urls[photoIdx] ?? card?.photo_urls[0] ?? null
  const Photo = card ? (
    <div className="flex flex-col gap-2">
      {photo ? (
        <img
          src={photo}
          alt={card.title}
          className="h-[200px] w-full rounded-2xl border border-hair bg-surface object-cover lg:h-[220px]"
        />
      ) : (
        <div className="flex h-[200px] flex-col items-center justify-center gap-2 rounded-2xl bg-surface lg:h-[220px]">
          <ShoppingBag className="h-[34px] w-[34px] text-text2 lg:h-[38px] lg:w-[38px]" strokeWidth={1.6} />
          <p className="text-[14px] text-text2">Фото не загружено</p>
        </div>
      )}
      {card.photo_urls.length > 1 && (
        <div className="flex gap-1.5 overflow-x-auto [scrollbar-width:none]">
          {card.photo_urls.map((url, i) => (
            <button
              key={i}
              type="button"
              aria-label={`Фото ${i + 1}`}
              onClick={() => setPhotoIdx(i)}
              className={cn(
                'h-12 w-16 shrink-0 overflow-hidden rounded-lg border',
                i === photoIdx ? 'border-amber' : 'border-hair opacity-70',
              )}
            >
              <img src={url} alt="" className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>
  ) : null

  const Upsell = card?.upsell ? (
    <div className="flex flex-col gap-1.5 rounded-[14px] border border-amber/45 bg-amber/10 p-3.5">
      <p className="text-[12px] font-bold uppercase tracking-[0.07em] text-text2">Что предложить вместе</p>
      <p className="whitespace-pre-wrap text-[16px] leading-[1.55] text-text [text-wrap:pretty]">{card.upsell}</p>
    </div>
  ) : null

  const Links =
    card && card.links.length > 0 ? (
      <div className="flex flex-col gap-2">
        {card.links.map((link) => (
          <Link
            key={`${link.object_type}-${link.object_id}`}
            to={link.url_path ?? '#'}
            className="flex flex-col gap-1 rounded-xl border border-hair bg-tint p-3.5 text-text transition-colors hover:border-amber/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
          >
            <span className="text-[11px] font-bold uppercase tracking-[0.09em] text-text2">Изучить по теме</span>
            <span className="flex items-center gap-2 text-[16px] font-semibold leading-[1.35]">
              <BookOpen className="h-4 w-4 shrink-0 text-text2" />
              <span className="min-w-0 flex-1">{link.title ?? 'Материал'}</span>
            </span>
          </Link>
        ))}
      </div>
    ) : null

  const Actions = canManage && card ? (
    <div className="flex flex-wrap gap-2">
      {/* Публикация — первым действием: до этой правки её искали внутри
          «Редактировать», и путь «завести товар» разрастался на два экрана. */}
      {productStatusActions(role, card.status).map((action) => (
        <Button
          key={action.to}
          variant="secondary"
          className={GHOST_BTN}
          disabled={setStatus.isPending}
          onClick={() =>
            void setStatus
              .mutateAsync(action.to)
              .then(() => toast.success(action.to === 'published' ? 'Опубликовано' : 'В архиве'))
          }
        >
          {action.to === 'published' ? (
            <Send className="h-4 w-4" />
          ) : (
            <Archive className="h-4 w-4" />
          )}{' '}
          {action.label}
        </Button>
      ))}
      <Button variant="secondary" className={GHOST_BTN} onClick={() => setEditing(true)}>
        <Pencil className="h-4 w-4" /> Редактировать
      </Button>
      {card.published_at === null && (
        <Button variant="secondary" className={cn(GHOST_BTN, 'text-red')} onClick={() => setDeleting(true)}>
          <Trash2 className="h-4 w-4" /> Удалить
        </Button>
      )}
    </div>
  ) : null

  return (
    <div className="mx-auto max-w-[920px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
      <button
        type="button"
        onClick={back}
        className="-ml-2.5 inline-flex min-h-11 items-center gap-[7px] rounded-lg px-2.5 text-[15px] font-semibold text-text hover:text-amber focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:min-h-10"
      >
        <ArrowLeft className="h-[17px] w-[17px]" strokeWidth={2.2} /> Ассортимент
      </button>

      {probe.isLoading && <SkeletonRows rows={6} />}
      {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}
      {data && !card && (
        <EmptyState
          layout="card"
          className="mt-4"
          icon={<ShoppingBag className="h-7 w-7" />}
          title="Позиция не найдена"
          text="Карточку сняли с публикации или ссылка устарела."
          cta="К ассортименту"
          onCta={back}
        />
      )}

      {card && (
        <div className="mt-[18px] flex flex-col gap-[18px] lg:mt-5 lg:grid lg:grid-cols-[300px_minmax(0,1fr)] lg:items-start lg:gap-7">
          {/* Мобильный порядок: фото → текст → действия → поля → upsell → ссылки.
              Десктоп: левая колонка фото + upsell + ссылки, правая — текст и поля. */}
          <div className="flex flex-col gap-3.5 lg:contents">
            <div className="lg:order-1 lg:flex lg:flex-col lg:gap-3.5">
              {Photo}
              <div className="hidden lg:flex lg:flex-col lg:gap-3.5">
                {Upsell}
                {Links}
              </div>
            </div>
          </div>
          <div className="flex min-w-0 flex-col gap-[18px] lg:order-2">
            <div>
              <h1 className="font-display text-[26px] font-bold leading-[1.2] tracking-[0.01em] text-text lg:text-[30px] lg:leading-[1.18]">
                {card.title}
              </h1>
              {card.status !== 'published' && (
                <Badge variant="outline" className="mt-2.5">
                  {CONTENT_STATUS_LABEL[card.status]}
                </Badge>
              )}
              {card.description && (
                <p className="mt-2.5 whitespace-pre-wrap text-[17px] leading-[1.65] text-text [text-wrap:pretty] lg:mt-3 lg:text-[18px] lg:leading-[1.7]">
                  {card.description}
                </p>
              )}
            </div>
            {Actions}
            {fields.length > 0 && (
              <dl className="flex flex-col gap-3 lg:gap-3.5">
                {fields.map(([name, value]) => (
                  <div
                    key={name}
                    className="flex flex-col gap-[3px] border-t border-hair pt-3 lg:grid lg:grid-cols-[160px_minmax(0,1fr)] lg:gap-4 lg:pt-3.5"
                  >
                    <dt className="text-[12px] font-bold uppercase tracking-[0.07em] text-text2">{name}</dt>
                    <dd className="whitespace-pre-wrap text-[16px] leading-[1.55] text-text lg:text-[17px] lg:leading-[1.6]">
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
            <div className="flex flex-col gap-3.5 lg:hidden">
              {Upsell}
              {Links}
            </div>
          </div>
        </div>
      )}

      {editing && card && (
        <ProductEditorDialog
          initial={card}
          categories={data?.categories ?? []}
          role={role}
          onClose={() => setEditing(false)}
        />
      )}
      {deleting && card && (
        <DeleteProductDialog
          card={card}
          onClose={() => setDeleting(false)}
          onDeleted={() => {
            setDeleting(false)
            back()
          }}
        />
      )}
    </div>
  )
}

function DeleteProductDialog({
  card,
  onClose,
  onDeleted,
}: {
  card: ProductCard
  onClose: () => void
  onDeleted: () => void
}) {
  const remove = useProductMutation(() => learnApi.deleteProduct(card.id))
  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={`Удалить «${card.title}»?`}
      description="Черновик удаляется насовсем. Опубликованную позицию снимают в архив — она исчезнет у сотрудников, история открытий сохранится."
      desktopWidth={440}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={remove.isPending}>
            Отмена
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => void remove.mutateAsync(undefined as never).then(onDeleted)}
          >
            Удалить
          </Button>
        </>
      }
    >
      <span className="sr-only">Подтверждение удаления</span>
    </ResponsiveDialog>
  )
}

// ─── Категории ───────────────────────────────────────────────────────────────

/**
 * ОС 19.08 «категории добавляются только через поддержку»: ручки
 * POST/PATCH/DELETE /learn/product-categories были с Ф4, не хватало экрана.
 * Устройство — как у разделов библиотеки: создание, переименование по месту,
 * удаление только пустой категории (сервер отвечает 409 с причиной).
 */
function CategoriesDialog({ categories, onClose }: { categories: ProductCategory[]; onClose: () => void }) {
  const [name, setName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const create = useProductMutation((title: string) => learnApi.createProductCategory(title))
  const rename = useProductMutation((args: { id: string; title: string }) =>
    learnApi.renameProductCategory(args.id, args.title),
  )
  const remove = useProductMutation((id: string) => learnApi.deleteProductCategory(id), 'Категория не удалена')

  const commitRename = () => {
    const trimmed = editingTitle.trim()
    if (editingId && trimmed) void rename.mutateAsync({ id: editingId, title: trimmed })
    setEditingId(null)
  }

  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title="Категории ассортимента"
      description="Удалить можно только пустую категорию — сначала перенесите её позиции."
      footer={
        <Button type="button" variant="secondary" onClick={onClose}>
          Закрыть
        </Button>
      }
    >
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (!name.trim()) return
          void create.mutateAsync(name.trim()).then(() => setName(''))
        }}
      >
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Новая категория…"
          maxLength={120}
          className="h-12 text-[15px] lg:h-11"
        />
        <Button type="submit" size="icon" className="h-12 w-12 shrink-0 lg:h-11 lg:w-11" disabled={!name.trim() || create.isPending} aria-label="Добавить">
          <Plus className="h-4 w-4" />
        </Button>
      </form>
      <ul className="divide-y divide-hair">
        {categories.length === 0 && <li className="py-3 text-[14px] text-text2">Категорий пока нет.</li>}
        {categories.map((c) => (
          <li key={c.id} className="flex min-h-12 items-center gap-2 py-1.5">
            {editingId === c.id ? (
              <Input
                autoFocus
                className="h-10 flex-1"
                value={editingTitle}
                onChange={(e) => setEditingTitle(e.target.value)}
                onBlur={commitRename}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    commitRename()
                  }
                  if (e.key === 'Escape') setEditingId(null)
                }}
              />
            ) : (
              <span className="min-w-0 flex-1 truncate text-[15px] text-text">{c.title}</span>
            )}
            <button
              type="button"
              title="Переименовать"
              aria-label={`Переименовать «${c.title}»`}
              className="flex h-10 w-10 items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text"
              onClick={() => {
                setEditingId(c.id)
                setEditingTitle(c.title)
              }}
            >
              <Pencil className="h-4 w-4" />
            </button>
            <button
              type="button"
              title="Удалить — только пустую категорию, без карточек"
              aria-label={`Удалить «${c.title}»`}
              className="flex h-10 w-10 items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-red"
              disabled={remove.isPending}
              onClick={() => void remove.mutateAsync(c.id)}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </li>
        ))}
      </ul>
    </ResponsiveDialog>
  )
}

// ─── Редактор карточки (manage) ──────────────────────────────────────────────

function ProductEditorDialog({
  initial,
  categories,
  defaultCategoryId = '',
  role,
  onSaved,
  onClose,
}: {
  initial: ProductCard | null
  categories: { id: string; title: string }[]
  /** Категория выбранного чипа: новый товар заводят «стоя» в ней. */
  defaultCategoryId?: string
  /** content_role: решает, показывать ли публикацию и аудиторию. */
  role: string
  /** Сохранённая карточка — списку: он покажет её и подсветит. */
  onSaved?: (card: ProductCard) => void
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [title, setTitle] = useState(initial?.title ?? '')
  const [categoryId, setCategoryId] = useState(initial?.category_id ?? defaultCategoryId)
  const [description, setDescription] = useState(initial?.description ?? '')
  const [composition, setComposition] = useState(initial?.composition ?? '')
  const [allergens, setAllergens] = useState(initial?.allergens ?? '')
  const [shelfLife, setShelfLife] = useState(initial?.shelf_life ?? '')
  const [serving, setServing] = useState(initial?.serving ?? '')
  const [upsell, setUpsell] = useState(initial?.upsell ?? '')
  // Существующие фото: URL уже подписаны; новые добавляются загрузкой.
  const [photos, setPhotos] = useState<{ media_id: string; url: string }[]>(() => {
    if (!initial) return []
    // media_id вытаскиваем из подписанного URL /api/media/{id}?...
    return initial.photo_urls
      .map((url) => {
        const m = /\/api\/media\/([0-9a-f-]{36})/.exec(url)
        return m ? { media_id: m[1]!, url } : null
      })
      .filter(Boolean) as { media_id: string; url: string }[]
  })
  const [links, setLinks] = useState(initial?.links ?? [])
  const [audienceOpen, setAudienceOpen] = useState(false)
  const [courseLinkOpen, setCourseLinkOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const photoInput = useRef<HTMLInputElement | null>(null)

  const buildBody = (): ProductUpsert & { title: string } => ({
    title: title.trim(),
    description: description.trim() || null,
    category_id: categoryId || null,
    composition: composition.trim() || null,
    allergens: allergens.trim() || null,
    shelf_life: shelfLife.trim() || null,
    serving: serving.trim() || null,
    upsell: upsell.trim() || null,
    photos: photos.map((p) => ({ media_id: p.media_id })),
    links: links.map((l) => ({ object_type: l.object_type, object_id: l.object_id })),
  })

  const save = useProductMutation(async (publish: boolean) => {
    const body = buildBody()
    if (initial) return learnApi.updateProduct(initial.id, body)
    const created = await learnApi.createProduct(body)
    if (!publish) return created
    try {
      return await learnApi.setProductStatus(created.id, 'published')
    } catch (err) {
      // Товар УЖЕ создан. Пробрасывать ошибку нельзя: форма осталась бы
      // открытой, и повторное нажатие завело бы дубль (уникального индекса
      // на названии в product_cards нет).
      toast.error('Товар создан, но опубликовать не удалось', {
        description: extractErrorDetail(err),
      })
      return created
    }
  })
  const setStatus = useProductMutation((status: 'published' | 'archived' | 'draft') =>
    learnApi.setProductStatus(initial!.id, status),
  )

  const submit = async (publish: boolean) => {
    const saved = await save.mutateAsync(publish).catch(() => null)
    if (!saved) return
    // Тост по фактическому статусу, а не по нажатой кнопке: при мягком
    // провале публикации он обязан сказать правду.
    toast.success(
      initial
        ? 'Сохранено'
        : saved.status === 'published'
          ? 'Товар опубликован'
          : 'Товар создан — черновик',
    )
    // ЖДЁМ перечитывания списка: плитка появится только после него, а
    // вызывающий к ней скроллит (useProductMutation инвалидирует через void).
    await qc.invalidateQueries({ queryKey: ['learn-products'] })
    onClose()
    onSaved?.(saved)
  }

  const onPhotoPick = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = [...(e.target.files ?? [])].slice(0, 10 - photos.length)
    e.target.value = ''
    if (!files.length) return
    setUploading(true)
    try {
      for (const file of files) {
        const media = await learnApi.uploadMedia(file)
        setPhotos((prev) => [...prev, { media_id: media.id, url: media.url }])
      }
    } catch (err) {
      toast.error('Не удалось загрузить фото', { description: extractErrorDetail(err) })
    } finally {
      setUploading(false)
    }
  }

  const canPublish = canPublishProduct(role)
  const valid = canSaveProduct(title)

  const FIELD = 'h-12 text-[15px] lg:h-11'
  const AREA =
    'flex w-full rounded-[10px] border border-glass-border bg-surface px-3.5 py-2.5 text-[15px] text-text focus-visible:border-amber focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber'

  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={initial ? 'Карточка товара' : 'Новый товар'}
      description={
        initial
          ? undefined
          : canPublish
            ? 'Черновик виден только тем, кто ведёт контент. «Сохранить и опубликовать» сразу отдаёт позицию сотрудникам.'
            : 'Позиция создаётся черновиком — сотрудники увидят её после публикации.'
      }
      desktopWidth={680}
      footer={
        <>
          {initial &&
            productStatusActions(role, initial.status).map((action) => (
              <Button
                key={action.to}
                type="button"
                variant="secondary"
                disabled={setStatus.isPending}
                onClick={() =>
                  void setStatus.mutateAsync(action.to).then(() => {
                    toast.success(action.to === 'published' ? 'Опубликовано' : 'В архиве')
                    onClose()
                  })
                }
              >
                {action.to === 'published' ? (
                  <Send className="h-4 w-4" />
                ) : (
                  <Archive className="h-4 w-4" />
                )}{' '}
                {action.label}
              </Button>
            ))}
          {initial && canEditProductAudience(role) && (
            <Button type="button" variant="secondary" onClick={() => setAudienceOpen(true)}>
              <Users className="h-4 w-4" /> Аудитория
            </Button>
          )}
          <span className="flex-1" />
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          {/* Обе кнопки под одним isPending: двойной клик по разным кнопкам
              иначе завёл бы два товара. */}
          {!initial && canPublish && (
            <Button
              type="button"
              variant="secondary"
              disabled={!valid || save.isPending}
              onClick={() => void submit(true)}
            >
              <Send className="h-4 w-4" /> Сохранить и опубликовать
            </Button>
          )}
          <Button
            type="button"
            disabled={!valid || save.isPending}
            onClick={() => void submit(false)}
          >
            {save.isPending ? 'Сохраняем…' : 'Сохранить'}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="p-title">Название</Label>
          <Input id="p-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} className={FIELD} autoFocus={!initial} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="p-category">Категория</Label>
          <SearchableSelect
            id="p-category"
            sheetTitle="Категория"
            placeholder="Без категории"
            clearLabel="Без категории"
            value={categoryId || null}
            onChange={(v) => setCategoryId(v ?? '')}
            className={FIELD}
            options={categories.map((c) => ({ value: c.id, label: c.title }))}
          />
        </div>
      </div>

      {(
        [
          ['Описание', description, setDescription],
          ['Состав', composition, setComposition],
          ['Аллергены', allergens, setAllergens],
          ['Срок годности', shelfLife, setShelfLife],
          ['Подача', serving, setServing],
          ['Что предложить вместе', upsell, setUpsell],
        ] as const
      ).map(([label, value, setter]) => (
        <div key={label} className="flex flex-col gap-1.5">
          <Label>{label}</Label>
          <textarea value={value} onChange={(e) => setter(e.target.value)} rows={2} className={AREA} />
        </div>
      ))}

      <div className="flex flex-col gap-1.5">
        <Label>Фото ({photos.length}/10)</Label>
        <div className="flex flex-wrap gap-2">
          {photos.map((photo, i) => (
            <div key={photo.media_id} className="relative">
              <img src={photo.url} alt="" className="h-16 w-20 rounded-lg border border-hair object-cover" />
              <button
                type="button"
                aria-label="Убрать фото"
                onClick={() => setPhotos((prev) => prev.filter((_, j) => j !== i))}
                className="absolute -right-1.5 -top-1.5 rounded-full bg-surface p-1 text-text2 shadow hover:text-red"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {photos.length < 10 && (
            <button
              type="button"
              disabled={uploading}
              onClick={() => photoInput.current?.click()}
              aria-label="Добавить фото"
              className="flex h-16 w-20 items-center justify-center rounded-lg border border-dashed border-glass-border text-text2 hover:border-amber/50 hover:text-text disabled:opacity-50"
            >
              <ImagePlus className="h-5 w-5" />
            </button>
          )}
        </div>
        <input
          ref={photoInput}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          hidden
          onChange={(e) => void onPhotoPick(e)}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>Изучить по теме</Label>
        <div className="flex flex-col gap-1.5">
          {links.map((link, i) => (
            <div
              key={`${link.object_type}-${link.object_id}`}
              className="flex min-h-11 items-center gap-2 rounded-[10px] border border-hair bg-surface px-3 text-[14px]"
            >
              <BookOpen className="h-4 w-4 shrink-0 text-text2" />
              <span className="min-w-0 flex-1 truncate text-text">{link.title ?? link.object_id}</span>
              <button
                type="button"
                aria-label="Убрать ссылку"
                onClick={() => setLinks((prev) => prev.filter((_, j) => j !== i))}
                className="flex h-9 w-9 items-center justify-center rounded-md text-text2 hover:text-red"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
          <Button variant="secondary" className="self-start bg-transparent" onClick={() => setCourseLinkOpen(true)}>
            <Plus className="h-4 w-4" /> Курс по теме
          </Button>
        </div>
      </div>

      {audienceOpen && initial && <ProductAudienceDialog card={initial} onClose={() => setAudienceOpen(false)} />}
      {courseLinkOpen && (
        <CoursePickDialog
          onClose={() => setCourseLinkOpen(false)}
          onPick={(id, courseTitle) => {
            setLinks((prev) =>
              prev.some((l) => l.object_type === 'course' && l.object_id === id)
                ? prev
                : [
                    ...prev,
                    {
                      object_type: 'course',
                      object_id: id,
                      title: courseTitle,
                      url_path: `/learn/courses/${id}`,
                    },
                  ],
            )
            setCourseLinkOpen(false)
          }}
        />
      )}
    </ResponsiveDialog>
  )
}

function ProductAudienceDialog({ card, onClose }: { card: ProductCard; onClose: () => void }) {
  const audience = useAudienceDraft(card.audience_id)
  const { value, setValue } = audience
  const save = useProductMutation(() => learnApi.setProductAudience(card.id, value))
  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={`Кому виден «${card.title}»`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            disabled={save.isPending || !audience.ready || audienceDraftProblem(value) !== null}
            onClick={() =>
              void save.mutateAsync(undefined as never).then(() => {
                toast.success('Аудитория обновлена')
                onClose()
              })
            }
          >
            Сохранить
          </Button>
        </>
      }
    >
      {audience.loading ? (
        <SkeletonRows rows={3} />
      ) : (
        <>
          {audience.failed && (
            <p className="text-[14px] text-red">
              Не удалось загрузить текущие правила — сохранение перезапишет их.
            </p>
          )}
          <AudiencePicker value={value} onChange={setValue} extraLabels={audience.extraLabels} />
        </>
      )}
    </ResponsiveDialog>
  )
}

function CoursePickDialog({ onClose, onPick }: { onClose: () => void; onPick: (courseId: string, title: string) => void }) {
  const courses = useCourses(true)
  return (
    <ResponsiveDialog open onOpenChange={(v) => !v && onClose()} title="Курс по теме" description="Ссылка появится в карточке блоком «Изучить по теме».">
      <div className="flex max-h-[60vh] flex-col gap-1.5 overflow-y-auto">
        {(courses.data?.items ?? []).map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => onPick(c.id, c.title)}
            className="flex min-h-12 w-full items-center gap-2 rounded-[10px] border border-hair px-3.5 text-left text-[15px] text-text hover:border-amber/50 lg:min-h-11"
          >
            <BookOpen className="h-4 w-4 shrink-0 text-text2" />
            <span className="min-w-0 flex-1 truncate">{c.title}</span>
            <Badge variant="outline">{CONTENT_STATUS_LABEL[c.status]}</Badge>
          </button>
        ))}
        {courses.isLoading && <SkeletonRows rows={3} />}
      </div>
    </ResponsiveDialog>
  )
}
