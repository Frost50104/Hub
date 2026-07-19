import {
  Archive,
  BookOpen,
  ImagePlus,
  Pencil,
  Plus,
  Send,
  ShoppingBag,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { useMemo, useRef, useState, type ChangeEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AudiencePicker, type AudienceValue } from '@/components/learn/AudiencePicker'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useCourses, useProductMutation, useProducts } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import {
  CONTENT_STATUS_LABEL,
  learnApi,
  type ProductCard,
  type ProductUpsert,
} from '@/lib/learn'

/**
 * Ассортимент (Ф4, ТЗ §9): каталог карточек товаров с фото, составом,
 * аллергенами и ссылками «изучить по теме». Открытие карточки фиксируется
 * (view_history + балл рейтинга за первое знакомство).
 */

export function LearnProductsPage() {
  const isDesktop = useIsDesktop()
  const [params, setParams] = useSearchParams()
  const [category, setCategory] = useState<string | 'all'>('all')
  const [openCard, setOpenCard] = useState<ProductCard | null>(null)
  const [editorCard, setEditorCard] = useState<ProductCard | 'new' | null>(null)

  const probe = useProducts(false)
  const canManage =
    probe.data !== undefined &&
    ['admin', 'publisher', 'author'].includes(probe.data.content_role)
  const managed = useProducts(true, canManage)
  const data = canManage ? (managed.data ?? probe.data) : probe.data

  const focusId = params.get('p')
  const items = useMemo(() => {
    let list = data?.items ?? []
    if (category !== 'all') list = list.filter((i) => i.category_id === category)
    return list
  }, [data, category])

  // Deep-link из поиска/новинок: ?p=<id> открывает карточку.
  const focused = focusId ? data?.items.find((i) => i.id === focusId) : undefined
  if (focused && !openCard && !editorCard) {
    setOpenCard(focused)
    const next = new URLSearchParams(params)
    next.delete('p')
    setParams(next, { replace: true })
  }

  return (
    <div className="mx-auto max-w-4xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Ассортимент" />}
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex items-center justify-between gap-2">
          {isDesktop && (
            <h1 className="font-display text-2xl font-bold text-text">Ассортимент</h1>
          )}
          {canManage && (
            <Button onClick={() => setEditorCard('new')}>
              <Plus className="h-4 w-4" /> Товар
            </Button>
          )}
        </div>

        {(data?.categories.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setCategory('all')}
              className={cn(
                'rounded-full border px-3 py-1 text-xs font-medium',
                category === 'all'
                  ? 'border-amber/60 bg-amber/10 text-amber'
                  : 'border-glass-border text-text2 hover:text-text',
              )}
            >
              Все
            </button>
            {data!.categories.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setCategory(c.id)}
                className={cn(
                  'rounded-full border px-3 py-1 text-xs font-medium',
                  category === c.id
                    ? 'border-amber/60 bg-amber/10 text-amber'
                    : 'border-glass-border text-text2 hover:text-text',
                )}
              >
                {c.title}
              </button>
            ))}
          </div>
        )}

        {probe.isLoading && <SkeletonRows rows={4} />}
        {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}

        {data && items.length === 0 && (
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <ShoppingBag className="mx-auto h-8 w-8 text-text3" />
            <p className="mt-3 text-sm text-text2">Карточек пока нет.</p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {items.map((card) => (
            <button
              key={card.id}
              type="button"
              onClick={() => {
                setOpenCard(card)
                if (card.status === 'published') void learnApi.openProduct(card.id)
              }}
              className="group overflow-hidden rounded-xl border border-glass-border bg-glass text-left transition-colors hover:border-amber/50"
            >
              {card.photo_urls[0] ? (
                <img
                  src={card.photo_urls[0]}
                  alt={card.title}
                  loading="lazy"
                  className="h-32 w-full object-cover sm:h-40"
                />
              ) : (
                <div className="flex h-32 w-full items-center justify-center bg-surface sm:h-40">
                  <ShoppingBag className="h-8 w-8 text-text3" />
                </div>
              )}
              <div className="p-2.5">
                <p className="truncate text-sm font-medium text-text">{card.title}</p>
                <div className="mt-1 flex items-center gap-1.5">
                  {card.status !== 'published' && (
                    <Badge variant="secondary">{CONTENT_STATUS_LABEL[card.status]}</Badge>
                  )}
                  {!card.viewed_by_me && card.status === 'published' && (
                    <span className="rounded bg-amber/15 px-1.5 py-0.5 text-[10px] font-medium text-amber">
                      новинка для вас
                    </span>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {openCard && (
        <ProductViewDialog
          card={openCard}
          canManage={canManage}
          onEdit={() => {
            setEditorCard(openCard)
            setOpenCard(null)
          }}
          onClose={() => setOpenCard(null)}
        />
      )}
      {editorCard !== null && (
        <ProductEditorDialog
          initial={editorCard === 'new' ? null : editorCard}
          categories={data?.categories ?? []}
          onClose={() => setEditorCard(null)}
        />
      )}
    </div>
  )
}

// ─── Просмотр карточки ───────────────────────────────────────────────────────

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-text3">{label}</p>
      <p className="whitespace-pre-wrap text-sm text-text2">{value}</p>
    </div>
  )
}

function ProductViewDialog({
  card,
  canManage,
  onEdit,
  onClose,
}: {
  card: ProductCard
  canManage: boolean
  onEdit: () => void
  onClose: () => void
}) {
  const [photoIdx, setPhotoIdx] = useState(0)
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between gap-2">
            <span>{card.title}</span>
            {canManage && (
              <button
                type="button"
                title="Редактировать"
                onClick={onEdit}
                className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text"
              >
                <Pencil className="h-4 w-4" />
              </button>
            )}
          </DialogTitle>
        </DialogHeader>

        {card.photo_urls.length > 0 && (
          <div className="space-y-1.5">
            <img
              src={card.photo_urls[photoIdx]}
              alt={card.title}
              className="max-h-72 w-full rounded-lg border border-glass-border object-cover"
            />
            {card.photo_urls.length > 1 && (
              <div className="flex gap-1.5 overflow-x-auto">
                {card.photo_urls.map((url, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setPhotoIdx(i)}
                    className={cn(
                      'h-12 w-16 shrink-0 overflow-hidden rounded border',
                      i === photoIdx ? 'border-amber' : 'border-glass-border opacity-70',
                    )}
                  >
                    <img src={url} alt="" className="h-full w-full object-cover" />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="space-y-2.5">
          {card.description && (
            <p className="whitespace-pre-wrap text-sm text-text">{card.description}</p>
          )}
          <Field label="Состав" value={card.composition} />
          <Field label="Аллергены" value={card.allergens} />
          <Field label="Сроки и хранение" value={card.shelf_life} />
          <Field label="Приготовление и подача" value={card.serving} />
          <Field label="Что предложить вместе" value={card.upsell} />

          {card.links.length > 0 && (
            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text3">
                Изучить по теме
              </p>
              <div className="space-y-1">
                {card.links.map((link) => (
                  <Link
                    key={`${link.object_type}-${link.object_id}`}
                    to={link.url_path ?? '#'}
                    onClick={onClose}
                    className="flex items-center gap-2 rounded-lg border border-glass-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:border-amber/50"
                  >
                    <BookOpen className="h-4 w-4 shrink-0 text-amber" />
                    <span className="min-w-0 flex-1 truncate">{link.title}</span>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ─── Редактор карточки (manage) ──────────────────────────────────────────────

function ProductEditorDialog({
  initial,
  categories,
  onClose,
}: {
  initial: ProductCard | null
  categories: { id: string; title: string }[]
  onClose: () => void
}) {
  const [title, setTitle] = useState(initial?.title ?? '')
  const [categoryId, setCategoryId] = useState(initial?.category_id ?? '')
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

  const save = useProductMutation(() =>
    initial
      ? learnApi.updateProduct(initial.id, buildBody())
      : learnApi.createProduct(buildBody()),
  )
  const setStatus = useProductMutation((status: 'published' | 'archived' | 'draft') =>
    learnApi.setProductStatus(initial!.id, status),
  )
  const remove = useProductMutation(() => learnApi.deleteProduct(initial!.id))

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

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{initial ? 'Карточка товара' : 'Новый товар'}</DialogTitle>
        </DialogHeader>

        <div className="space-y-2.5">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div>
              <Label htmlFor="p-title">Название</Label>
              <Input
                id="p-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={255}
              />
            </div>
            <div>
              <Label htmlFor="p-category">Категория</Label>
              <Select
                id="p-category"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
              >
                <option value="">Без категории</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {(
            [
              ['Описание', description, setDescription],
              ['Состав', composition, setComposition],
              ['Аллергены', allergens, setAllergens],
              ['Сроки и хранение', shelfLife, setShelfLife],
              ['Приготовление и подача', serving, setServing],
              ['Что предложить вместе', upsell, setUpsell],
            ] as const
          ).map(([label, value, setter]) => (
            <div key={label}>
              <Label>{label}</Label>
              <textarea
                value={value}
                onChange={(e) => setter(e.target.value)}
                rows={2}
                className="flex w-full rounded-lg border border-glass-border bg-glass px-3 py-2 text-sm text-text focus-visible:border-amber focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber"
              />
            </div>
          ))}

          <div>
            <Label>Фото ({photos.length}/10)</Label>
            <div className="flex flex-wrap gap-1.5">
              {photos.map((photo, i) => (
                <div key={photo.media_id} className="relative">
                  <img
                    src={photo.url}
                    alt=""
                    className="h-16 w-20 rounded border border-glass-border object-cover"
                  />
                  <button
                    type="button"
                    aria-label="Убрать фото"
                    onClick={() => setPhotos((prev) => prev.filter((_, j) => j !== i))}
                    className="absolute -right-1.5 -top-1.5 rounded-full bg-surface p-0.5 text-text3 shadow hover:text-red"
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
                  className="flex h-16 w-20 items-center justify-center rounded border border-dashed border-glass-border text-text3 hover:border-amber/50 hover:text-text disabled:opacity-50"
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

          <div>
            <Label>Изучить по теме</Label>
            <div className="space-y-1">
              {links.map((link, i) => (
                <div
                  key={`${link.object_type}-${link.object_id}`}
                  className="flex items-center gap-2 rounded-lg border border-glass-border bg-surface px-3 py-1.5 text-sm"
                >
                  <BookOpen className="h-4 w-4 shrink-0 text-amber" />
                  <span className="min-w-0 flex-1 truncate text-text">
                    {link.title ?? link.object_id}
                  </span>
                  <button
                    type="button"
                    aria-label="Убрать ссылку"
                    onClick={() => setLinks((prev) => prev.filter((_, j) => j !== i))}
                    className="rounded p-1 text-text3 hover:text-red"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              ))}
              <Button size="sm" variant="ghost" onClick={() => setCourseLinkOpen(true)}>
                + курс по теме
              </Button>
            </div>
          </div>
        </div>

        <DialogFooter className="flex-wrap gap-2">
          {initial && initial.status !== 'published' && (
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                void setStatus.mutateAsync('published').then(() => {
                  toast.success('Опубликовано')
                  onClose()
                })
              }
            >
              <Send className="h-4 w-4" /> Опубликовать
            </Button>
          )}
          {initial && initial.status === 'published' && (
            <Button
              type="button"
              variant="ghost"
              onClick={() =>
                void setStatus.mutateAsync('archived').then(() => {
                  toast.success('В архиве')
                  onClose()
                })
              }
            >
              <Archive className="h-4 w-4" /> В архив
            </Button>
          )}
          {initial && (
            <Button type="button" variant="ghost" onClick={() => setAudienceOpen(true)}>
              <Users className="h-4 w-4" /> Аудитория
            </Button>
          )}
          {initial && initial.published_at === null && (
            <Button
              type="button"
              variant="ghost"
              className="text-red"
              onClick={() => {
                if (!window.confirm(`Удалить «${initial.title}»?`)) return
                void remove.mutateAsync(undefined as never).then(onClose)
              }}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
          <span className="flex-1" />
          <Button type="button" variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button
            type="button"
            disabled={!title.trim() || save.isPending}
            onClick={() =>
              void save.mutateAsync(undefined as never).then(() => {
                toast.success('Сохранено')
                onClose()
              })
            }
          >
            Сохранить
          </Button>
        </DialogFooter>

        {audienceOpen && initial && (
          <ProductAudienceDialog card={initial} onClose={() => setAudienceOpen(false)} />
        )}
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
      </DialogContent>
    </Dialog>
  )
}

function ProductAudienceDialog({
  card,
  onClose,
}: {
  card: ProductCard
  onClose: () => void
}) {
  const [value, setValue] = useState<AudienceValue>({
    is_all: card.audience_id === null,
    rules: [],
  })
  const save = useProductMutation(() => learnApi.setProductAudience(card.id, value))
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Кому виден «{card.title}»</DialogTitle>
        </DialogHeader>
        <AudiencePicker value={value} onChange={setValue} />
        <DialogFooter>
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            disabled={save.isPending}
            onClick={() =>
              void save.mutateAsync(undefined as never).then(() => {
                toast.success('Аудитория обновлена')
                onClose()
              })
            }
          >
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CoursePickDialog({
  onClose,
  onPick,
}: {
  onClose: () => void
  onPick: (courseId: string, title: string) => void
}) {
  const courses = useCourses(true)
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Курс по теме</DialogTitle>
        </DialogHeader>
        <div className="max-h-72 space-y-1 overflow-y-auto">
          {(courses.data?.items ?? []).map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => onPick(c.id, c.title)}
              className="flex w-full items-center gap-2 rounded-lg border border-glass-border px-3 py-2 text-left text-sm text-text hover:border-amber/50"
            >
              <BookOpen className="h-4 w-4 shrink-0 text-amber" />
              <span className="min-w-0 flex-1 truncate">{c.title}</span>
              <Badge variant="secondary">{CONTENT_STATUS_LABEL[c.status]}</Badge>
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
