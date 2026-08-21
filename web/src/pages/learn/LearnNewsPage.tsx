import {
  Archive,
  Check,
  MessageCircle,
  Newspaper,
  Pin,
  Plus,
  Send,
  Star,
  Trash2,
  Users,
} from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AudiencePicker, useAudienceDraft } from '@/components/learn/AudiencePicker'
import { RichRenderer, type RichDoc } from '@/components/learn/rich/RichRenderer'
import { QueryError } from '@/components/QueryError'
import { ActionRow } from '@/components/ui/ActionRow'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useNews, useNewsMutation } from '@/hooks/useLearn'
import { useMe } from '@/hooks/useMe'
import { cn } from '@/lib/cn'
import {
  CONTENT_STATUS_LABEL,
  learnApi,
  REACTION_EMOJIS,
  type NewsComment,
  type NewsPost,
} from '@/lib/learn'
import { nbsp, plural } from '@/lib/typography'

// TipTap-редактор — отдельный chunk, грузится только при открытии формы.
const RichEditor = lazy(() => import('@/components/learn/rich/RichEditor'))

const PIN_DAYS = 30

function formatWhen(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

function isPinned(post: NewsPost): boolean {
  return post.pinned_until !== null && new Date(post.pinned_until).getTime() > Date.now()
}

/** Ряд действий: 48px на телефоне (тап-цель), 36px в плотной ленте десктопа. */
const ACTION_BTN =
  'h-12 rounded-xl px-5 text-[15px] lg:h-9 lg:rounded-[10px] lg:px-3.5 lg:text-[13px]'
const GHOST_BTN = cn(ACTION_BTN, 'bg-transparent')

/**
 * Новости по макету «Урок — редизайн» (route news): лента карточек 16/tint,
 * закреплённая — единственная с амбер-рамкой (она требует действия),
 * остальные на `--hair`. Управляющему — «+ Новая новость», черновики под
 * заголовком и ряд действий под каждой карточкой (`ActionRow`), а не
 * карандаш в шапке: текстовая колонка не сжимается иконками.
 */
export function LearnNewsPage() {
  const [params, setParams] = useSearchParams()
  const [formPost, setFormPost] = useState<NewsPost | 'new' | null>(null)

  const probe = useNews(false)
  const canManage =
    probe.data !== undefined && ['admin', 'publisher', 'author'].includes(probe.data.content_role)
  const managed = useNews(true, canManage)
  const data = canManage ? (managed.data ?? probe.data) : probe.data
  const isPublisher = data !== undefined && ['admin', 'publisher'].includes(data.content_role)

  const focusId = params.get('p')
  const { feed, drafts } = useMemo(() => {
    const items = data?.items ?? []
    const published = items.filter((p) => p.status === 'published')
    const rest = items.filter((p) => p.status !== 'published')
    if (!focusId) return { feed: published, drafts: rest }
    // Deep-link из уведомления — фокусный пост поднимаем наверх.
    const focus = published.find((p) => p.id === focusId)
    return {
      feed: focus ? [focus, ...published.filter((p) => p.id !== focusId)] : published,
      drafts: rest,
    }
  }, [data, focusId])

  const ackPending = feed.filter((p) => p.ack_pending).length
  const counter =
    feed.length === 0
      ? ''
      : nbsp(
          `${plural(feed.length, 'новость', 'новости', 'новостей')} · ${
            ackPending > 0
              ? `${plural(ackPending, 'требует', 'требуют', 'требуют')} ознакомления`
              : 'всё прочитано'
          }`,
        )

  const clearFocus = () => {
    const next = new URLSearchParams(params)
    next.delete('p')
    setParams(next, { replace: true })
  }

  return (
    <div className="mx-auto max-w-[760px] px-5 pb-16 pt-11 lg:px-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          {counter && <p className="mb-1 text-[12px] leading-[1.35] text-text2 lg:hidden">{counter}</p>}
          <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
            Новости
          </h1>
          {counter && (
            <p className="mt-2.5 hidden text-[18px] leading-[1.6] text-text2 lg:block">{counter}</p>
          )}
        </div>
        {canManage && (
          <Button onClick={() => setFormPost('new')} className="hidden shrink-0 lg:inline-flex">
            <Plus className="h-4 w-4" /> Новость
          </Button>
        )}
      </header>

      {canManage && (
        <div className="mt-4 flex flex-col gap-2.5">
          <Button onClick={() => setFormPost('new')} className="h-12 w-full rounded-xl text-[15px] lg:hidden">
            <Plus className="h-[18px] w-[18px]" /> Новая новость
          </Button>
          {drafts.map((post) => (
            <DraftRow
              key={post.id}
              post={post}
              isPublisher={isPublisher}
              onEdit={() => setFormPost(post)}
            />
          ))}
        </div>
      )}

      <div className="mt-[18px] flex flex-col gap-3 lg:mt-[22px] lg:gap-[22px]">
        {probe.isLoading && <SkeletonRows rows={6} />}
        {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}
        {data && feed.length === 0 && !probe.isLoading && (
          <EmptyState
            layout="card"
            icon={<Newspaper className="h-7 w-7" />}
            title="Новостей пока нет"
            text={
              canManage
                ? 'Первая новость появится здесь сразу после публикации.'
                : 'Когда компания что-то объявит, новость появится здесь и на витрине.'
            }
          />
        )}
        {data &&
          feed.map((post) => (
            <NewsCard
              key={post.id}
              post={post}
              contentRole={data.content_role}
              highlighted={post.id === focusId}
              onEdit={() => setFormPost(post)}
              onFocusClear={clearFocus}
            />
          ))}
      </div>

      {formPost !== null && (
        <NewsFormDialog
          key={formPost === 'new' ? 'new' : formPost.id}
          post={formPost === 'new' ? null : formPost}
          onClose={() => setFormPost(null)}
        />
      )}
    </div>
  )
}

// ─── Черновик под заголовком ─────────────────────────────────────────────────

function DraftRow({
  post,
  isPublisher,
  onEdit,
}: {
  post: NewsPost
  isPublisher: boolean
  onEdit: () => void
}) {
  const setStatus = useNewsMutation((s: string) => learnApi.setNewsStatus(post.id, s as never))
  const remove = useNewsMutation(() => learnApi.deleteNews(post.id))
  const [audienceOpen, setAudienceOpen] = useState(false)
  return (
    <div className="flex flex-wrap items-center gap-2.5 rounded-[14px] border border-dashed border-glass-border px-3.5 py-2.5 lg:py-2">
      <Badge variant={post.status === 'review' ? 'secondary' : 'outline'}>
        {CONTENT_STATUS_LABEL[post.status]}
      </Badge>
      <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-text">{post.title}</span>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" size="md" className="bg-transparent" onClick={onEdit}>
          Изменить
        </Button>
        {isPublisher && post.status !== 'archived' && (
          <Button
            size="md"
            disabled={setStatus.isPending}
            onClick={() =>
              void setStatus.mutateAsync('published').then(() => toast.success('Новость опубликована'))
            }
          >
            <Send className="h-3.5 w-3.5" /> Опубликовать
          </Button>
        )}
        {isPublisher && (
          <Button variant="secondary" size="md" className="bg-transparent" onClick={() => setAudienceOpen(true)}>
            <Users className="h-3.5 w-3.5" /> Аудитория
          </Button>
        )}
        {post.published_at === null && (
          <Button
            variant="secondary"
            size="md"
            className="bg-transparent text-red"
            disabled={remove.isPending}
            onClick={() => void remove.mutateAsync(undefined as never)}
          >
            <Trash2 className="h-3.5 w-3.5" /> Удалить
          </Button>
        )}
      </div>
      {audienceOpen && <NewsAudienceDialog post={post} onClose={() => setAudienceOpen(false)} />}
    </div>
  )
}

// ─── Карточка поста ──────────────────────────────────────────────────────────

function NewsCard({
  post,
  contentRole,
  highlighted,
  onEdit,
  onFocusClear,
}: {
  post: NewsPost
  contentRole: string
  highlighted: boolean
  onEdit: () => void
  onFocusClear: () => void
}) {
  const me = useMe()
  const isPublisher = ['admin', 'publisher'].includes(contentRole)
  const canManage = isPublisher || (contentRole === 'author' && post.status !== 'published')
  const pinned = isPinned(post)
  const [commentsOpen, setCommentsOpen] = useState(false)
  const [audienceOpen, setAudienceOpen] = useState(false)

  const react = useNewsMutation((emoji: string) => learnApi.toggleReaction(post.id, emoji))
  const ack = useNewsMutation(() => learnApi.ackNews(post.id))
  const setStatus = useNewsMutation((s: string) => learnApi.setNewsStatus(post.id, s as never))
  const favorite = useNewsMutation(() => learnApi.toggleFavorite('news_post', post.id))
  const pin = useNewsMutation(() =>
    learnApi.updateNews(post.id, {
      pinned_until: pinned
        ? null
        : new Date(Date.now() + PIN_DAYS * 24 * 60 * 60 * 1000).toISOString(),
    }),
  )

  return (
    <article
      className={cn(
        'flex flex-col gap-2.5 rounded-2xl border bg-tint p-4',
        // Закреплённый — единственная карточка с амбер-рамкой: она требует
        // действия. Остальные — на нейтральной --hair.
        pinned ? 'border-amber/55' : 'border-hair',
        highlighted && 'ring-1 ring-amber/40',
      )}
      onClick={highlighted ? onFocusClear : undefined}
    >
      {pinned && (
        <Badge className="gap-1.5 self-start" title={`Закреплено до ${formatDay(post.pinned_until!)}`}>
          <Pin className="h-3 w-3" /> Закреплено
        </Badge>
      )}
      <div>
        <h2 className="text-[17px] font-semibold leading-[1.3] text-text [text-wrap:pretty] lg:font-display lg:text-[20px] lg:font-bold lg:leading-[1.28]">
          {post.title}
        </h2>
        <p className="mt-1.5 text-[13px] leading-[1.4] text-text2 lg:text-[14px]">
          {[post.author_name, formatWhen(post.published_at ?? post.created_at)]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </div>

      <RichRenderer value={post.body as RichDoc} className="[&>:last-child]:mb-0" />

      {post.ack_pending && (
        <div className="flex flex-col gap-2.5 rounded-xl border border-amber/45 bg-amber/10 p-3 lg:flex-row lg:flex-wrap lg:items-center lg:justify-between lg:px-3.5">
          <p className="min-w-0 flex-1 text-[15px] leading-[1.45] text-text">
            Требуется подтвердить ознакомление
          </p>
          <Button
            disabled={ack.isPending}
            className="h-12 rounded-xl text-[15px] lg:h-10 lg:rounded-[10px]"
            onClick={() =>
              void ack.mutateAsync(undefined as never).then(() => {
                toast.success('Ознакомление подтверждено')
              })
            }
          >
            <Check className="h-[17px] w-[17px]" /> Ознакомлен
          </Button>
        </div>
      )}
      {post.requires_acknowledgement && post.acked_by_me && (
        <p className="flex items-center gap-[7px] text-[14px] text-green-deep">
          <Check className="h-4 w-4" /> Ознакомление подтверждено
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {post.allow_reactions &&
          REACTION_EMOJIS.map((emoji) => {
            const count = post.reactions[emoji] ?? 0
            const mine = post.my_reactions.includes(emoji)
            return (
              <button
                key={emoji}
                type="button"
                aria-pressed={mine}
                onClick={() => void react.mutateAsync(emoji)}
                className={cn(
                  'inline-flex min-h-9 items-center gap-1.5 rounded-full border px-[11px] text-[15px] transition-colors',
                  mine ? 'border-amber/55 bg-amber/15' : 'border-hair bg-transparent hover:border-amber/40',
                )}
              >
                {emoji}
                {count > 0 && <span className="text-[13px] font-semibold text-text2">{count}</span>}
              </button>
            )
          })}
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            title={post.is_favorite ? 'Убрать из избранного' : 'В избранное'}
            aria-pressed={post.is_favorite}
            className="inline-flex h-9 w-9 items-center justify-center rounded-full text-text2 hover:bg-glass hover:text-amber focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            onClick={() => void favorite.mutateAsync(undefined as never)}
          >
            <Star className={cn('h-4 w-4', post.is_favorite && 'fill-amber text-amber')} />
          </button>
          {post.allow_comments && (
            <button
              type="button"
              aria-expanded={commentsOpen}
              onClick={() => setCommentsOpen((v) => !v)}
              className="inline-flex min-h-9 items-center gap-[7px] rounded-full border border-hair px-[11px] text-[14px] font-semibold text-text2 hover:text-text"
            >
              <MessageCircle className="h-[15px] w-[15px]" />
              {post.comments_count > 0 ? post.comments_count : 'Комментировать'}
            </button>
          )}
        </div>
      </div>

      {commentsOpen && <CommentsBlock post={post} myName={me.data?.full_name ?? ''} />}

      {canManage && (
        <ActionRow className="mt-0">
          {isPublisher && (
            <Button
              variant="secondary"
              className={GHOST_BTN}
              disabled={pin.isPending}
              onClick={() =>
                void pin.mutateAsync(undefined as never).then(() =>
                  toast.success(pinned ? 'Новость откреплена' : `Закреплено на ${PIN_DAYS} дней`),
                )
              }
            >
              {pinned ? 'Открепить' : 'Закрепить'}
            </Button>
          )}
          <Button variant="secondary" className={GHOST_BTN} onClick={onEdit}>
            Изменить
          </Button>
          {isPublisher && (
            <Button variant="secondary" className={GHOST_BTN} onClick={() => setAudienceOpen(true)}>
              <Users className="h-3.5 w-3.5" /> Аудитория
            </Button>
          )}
          {isPublisher && (
            <Button
              variant="secondary"
              className={cn(GHOST_BTN, 'text-red')}
              disabled={setStatus.isPending}
              onClick={() =>
                void setStatus.mutateAsync('archived').then(() => toast.success('Новость снята с публикации'))
              }
            >
              <Archive className="h-3.5 w-3.5" /> Снять с публикации
            </Button>
          )}
        </ActionRow>
      )}

      {audienceOpen && <NewsAudienceDialog post={post} onClose={() => setAudienceOpen(false)} />}
    </article>
  )
}

// ─── Комментарии ─────────────────────────────────────────────────────────────

function CommentsBlock({ post, myName }: { post: NewsPost; myName: string }) {
  const [comments, setComments] = useState<NewsComment[] | null>(null)
  const [text, setText] = useState('')
  const [error, setError] = useState(false)

  useEffect(() => {
    learnApi
      .newsComments(post.id)
      .then(setComments)
      .catch(() => setError(true))
  }, [post.id])

  const send = useNewsMutation(async () => {
    const comment = await learnApi.addNewsComment(post.id, text.trim())
    setComments((prev) => [...(prev ?? []), { ...comment, author_name: myName }])
    setText('')
  })

  return (
    <div className="flex flex-col gap-2 border-t border-hair pt-3">
      {error && <p className="text-[13px] text-red">Не удалось загрузить комментарии.</p>}
      {comments === null && !error && <SkeletonRows rows={2} />}
      {(comments ?? []).map((c) => (
        <div key={c.id} className="rounded-lg bg-surface px-3 py-2">
          <p className="text-[12px] font-medium text-text2">
            {c.author_name ?? '—'}{' '}
            <span className="font-normal">{formatWhen(c.created_at)}</span>
          </p>
          <p className="mt-0.5 text-[15px] leading-[1.45] text-text">
            {c.deleted_at ? <span className="italic text-text2">Комментарий удалён</span> : c.body}
          </p>
        </div>
      ))}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (text.trim()) void send.mutateAsync(undefined as never)
        }}
      >
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Написать комментарий…"
          className="h-11 lg:h-10"
        />
        <Button type="submit" size="icon" className="h-11 w-11 shrink-0 lg:h-10 lg:w-10" disabled={!text.trim() || send.isPending} aria-label="Отправить">
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  )
}

// ─── Форма поста ─────────────────────────────────────────────────────────────

function NewsFormDialog({ post, onClose }: { post: NewsPost | null; onClose: () => void }) {
  const isNew = post === null
  const [title, setTitle] = useState(post?.title ?? '')
  const [body, setBody] = useState<RichDoc>(
    (post?.body as RichDoc) ?? {
      schema: 1,
      doc: { type: 'doc', content: [{ type: 'paragraph' }] },
    },
  )
  const [allowComments, setAllowComments] = useState(post?.allow_comments ?? true)
  const [allowReactions, setAllowReactions] = useState(post?.allow_reactions ?? true)
  const [requiresAck, setRequiresAck] = useState(post?.requires_acknowledgement ?? false)

  const save = useNewsMutation(() =>
    isNew
      ? learnApi.createNews({
          title: title.trim(),
          body,
          allow_comments: allowComments,
          allow_reactions: allowReactions,
          requires_acknowledgement: requiresAck,
        })
      : learnApi.updateNews(post.id, {
          title: title.trim(),
          body,
          allow_comments: allowComments,
          allow_reactions: allowReactions,
          requires_acknowledgement: requiresAck,
        }),
  )

  const submit = () => {
    if (!title.trim()) return
    void save.mutateAsync(undefined as never).then(() => {
      toast.success(isNew ? 'Новость создана (черновик)' : 'Сохранено')
      onClose()
    })
  }

  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={isNew ? 'Новая новость' : 'Изменить новость'}
      description={
        isNew ? 'Новость создаётся черновиком — сотрудники увидят её после публикации.' : undefined
      }
      desktopWidth={680}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button type="button" onClick={submit} disabled={!title.trim() || save.isPending}>
            {save.isPending ? 'Сохраняем…' : 'Сохранить'}
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="news-title">Заголовок</Label>
          <Input
            id="news-title"
            autoFocus={isNew}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="h-12 text-[15px] lg:h-11"
          />
        </div>
        <Suspense fallback={<SkeletonRows rows={4} />}>
          <RichEditor value={body} onChange={setBody} placeholder="Текст новости…" />
        </Suspense>
        <div className="flex flex-wrap gap-x-5 gap-y-3">
          {(
            [
              ['Комментарии', allowComments, setAllowComments],
              ['Реакции', allowReactions, setAllowReactions],
              ['Обязательное ознакомление', requiresAck, setRequiresAck],
            ] as const
          ).map(([label, checked, set]) => (
            <label key={label} className="flex min-h-11 cursor-pointer items-center gap-2.5 text-[15px] text-text">
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => set(e.target.checked)}
                className="h-[18px] w-[18px] accent-[#FFB200]"
              />
              {label}
            </label>
          ))}
        </div>
      </form>
    </ResponsiveDialog>
  )
}

function NewsAudienceDialog({ post, onClose }: { post: NewsPost; onClose: () => void }) {
  const audience = useAudienceDraft(post.audience_id)
  const { value, setValue } = audience
  const save = useNewsMutation(() => learnApi.setNewsAudience(post.id, value))
  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={`Кому видна «${post.title}»`}
      description={post.audience_id !== null ? 'Правила ниже заменят текущие.' : undefined}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            type="button"
            disabled={save.isPending || !audience.ready}
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
