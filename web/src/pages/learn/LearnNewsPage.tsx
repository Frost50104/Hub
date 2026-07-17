import {
  Archive,
  Check,
  MessageCircle,
  Newspaper,
  Pencil,
  Plus,
  Send,
  Star,
  Trash2,
  Users,
} from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AudiencePicker, type AudienceValue } from '@/components/learn/AudiencePicker'
import { RichRenderer, type RichDoc } from '@/components/learn/rich/RichRenderer'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useNews, useNewsMutation } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import { cn } from '@/lib/cn'
import {
  CONTENT_STATUS_LABEL,
  learnApi,
  REACTION_EMOJIS,
  type NewsComment,
  type NewsPost,
} from '@/lib/learn'

// TipTap-редактор — отдельный chunk, грузится только при открытии формы.
const RichEditor = lazy(() => import('@/components/learn/rich/RichEditor'))

function formatWhen(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function LearnNewsPage() {
  const isDesktop = useIsDesktop()
  const [params, setParams] = useSearchParams()
  const [formPost, setFormPost] = useState<NewsPost | 'new' | null>(null)

  const probe = useNews(false)
  const canManage =
    probe.data !== undefined && ['admin', 'publisher', 'author'].includes(probe.data.content_role)
  const managed = useNews(true, canManage)
  const data = canManage ? (managed.data ?? probe.data) : probe.data

  const focusId = params.get('p')
  const posts = useMemo(() => {
    const items = data?.items ?? []
    if (!focusId) return items
    // Deep-link из уведомления — фокусный пост поднимаем наверх.
    const focus = items.find((p) => p.id === focusId)
    return focus ? [focus, ...items.filter((p) => p.id !== focusId)] : items
  }, [data, focusId])

  return (
    <div className="mx-auto max-w-3xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Новости" />}
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex items-center justify-between gap-2">
          {isDesktop && (
            <h1 className="font-display text-2xl font-bold text-text">Новости</h1>
          )}
          {canManage && (
            <Button onClick={() => setFormPost('new')}>
              <Plus className="h-4 w-4" /> Новость
            </Button>
          )}
        </div>

        {probe.isLoading && <SkeletonRows rows={6} />}
        {probe.isError && <QueryError onRetry={() => void probe.refetch()} />}
        {data && posts.length === 0 && (
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <Newspaper className="mx-auto h-8 w-8 text-text3" />
            <p className="mt-3 text-sm text-text2">Новостей пока нет.</p>
          </div>
        )}

        {data &&
          posts.map((post) => (
            <NewsCard
              key={post.id}
              post={post}
              contentRole={data.content_role}
              highlighted={post.id === focusId}
              onEdit={() => setFormPost(post)}
              onFocusClear={() => {
                const next = new URLSearchParams(params)
                next.delete('p')
                setParams(next, { replace: true })
              }}
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
  const canManage =
    isPublisher || (contentRole === 'author' && post.status !== 'published')
  const [commentsOpen, setCommentsOpen] = useState(false)
  const [audienceOpen, setAudienceOpen] = useState(false)

  const react = useNewsMutation((emoji: string) => learnApi.toggleReaction(post.id, emoji))
  const ack = useNewsMutation(() => learnApi.ackNews(post.id))
  const setStatus = useNewsMutation((s: string) =>
    learnApi.setNewsStatus(post.id, s as never),
  )
  const favorite = useNewsMutation(() => learnApi.toggleFavorite('news_post', post.id))
  const remove = useNewsMutation(() => learnApi.deleteNews(post.id))

  return (
    <article
      className={cn(
        'rounded-xl border border-glass-border bg-glass p-4',
        highlighted && 'border-amber/60 ring-1 ring-amber/40',
      )}
      onClick={highlighted ? onFocusClear : undefined}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-text">{post.title}</h2>
          <p className="mt-0.5 text-xs text-text3">
            {[post.author_name, formatWhen(post.published_at ?? post.created_at)]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {post.status !== 'published' && (
            <Badge variant="outline" className="text-text3">
              {CONTENT_STATUS_LABEL[post.status]}
            </Badge>
          )}
          <button
            title={post.is_favorite ? 'Убрать из избранного' : 'В избранное'}
            className="rounded p-1.5 text-text3 hover:bg-glass hover:text-amber"
            onClick={() => void favorite.mutateAsync(undefined as never)}
          >
            <Star
              className={cn('h-4 w-4', post.is_favorite && 'fill-amber text-amber')}
            />
          </button>
          {canManage && (
            <button
              title="Изменить"
              className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text"
              onClick={onEdit}
            >
              <Pencil className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      <RichRenderer value={post.body as RichDoc} className="mt-2" />

      {post.ack_pending && (
        <div className="mt-3 flex items-center justify-between gap-2 rounded-lg border border-amber/40 bg-amber/10 px-3 py-2">
          <span className="text-sm text-text">Требуется подтвердить ознакомление</span>
          <Button
            disabled={ack.isPending}
            onClick={() =>
              void ack.mutateAsync(undefined as never).then(() => {
                toast.success('Ознакомление подтверждено')
              })
            }
          >
            <Check className="h-4 w-4" /> Ознакомлен
          </Button>
        </div>
      )}
      {post.requires_acknowledgement && post.acked_by_me && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-green">
          <Check className="h-3.5 w-3.5" /> Ознакомление подтверждено
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {post.allow_reactions &&
          REACTION_EMOJIS.map((emoji) => {
            const count = post.reactions[emoji] ?? 0
            const mine = post.my_reactions.includes(emoji)
            if (count === 0 && !mine && post.status !== 'published') return null
            return (
              <button
                key={emoji}
                onClick={() => void react.mutateAsync(emoji)}
                className={cn(
                  'flex items-center gap-1 rounded-full border px-2 py-0.5 text-sm transition-colors',
                  mine
                    ? 'border-amber/60 bg-amber/15'
                    : 'border-glass-border bg-glass hover:border-amber/40',
                )}
              >
                {emoji}
                {count > 0 && <span className="text-xs text-text2">{count}</span>}
              </button>
            )
          })}
        {post.allow_comments && (
          <button
            onClick={() => setCommentsOpen((v) => !v)}
            className="ml-auto flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs text-text3 hover:text-text"
          >
            <MessageCircle className="h-3.5 w-3.5" />
            {post.comments_count > 0 ? post.comments_count : 'Комментировать'}
          </button>
        )}
      </div>

      {commentsOpen && <CommentsBlock post={post} myName={me.data?.full_name ?? ''} />}

      {canManage && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-glass-border pt-3">
          {isPublisher && post.status !== 'published' && (
            <Button
              disabled={setStatus.isPending}
              onClick={() =>
                void setStatus.mutateAsync('published').then(() => {
                  toast.success('Новость опубликована')
                })
              }
            >
              <Send className="h-3.5 w-3.5" /> Опубликовать
            </Button>
          )}
          {isPublisher && post.status === 'published' && (
            <Button
              variant="secondary"
              disabled={setStatus.isPending}
              onClick={() => void setStatus.mutateAsync('archived')}
            >
              <Archive className="h-3.5 w-3.5" /> В архив
            </Button>
          )}
          {isPublisher && (
            <Button variant="secondary" onClick={() => setAudienceOpen(true)}>
              <Users className="h-3.5 w-3.5" /> Аудитория
            </Button>
          )}
          {post.published_at === null && (
            <Button
              variant="secondary"
              className="text-red"
              disabled={remove.isPending}
              onClick={() => void remove.mutateAsync(undefined as never)}
            >
              <Trash2 className="h-3.5 w-3.5" /> Удалить
            </Button>
          )}
        </div>
      )}

      {audienceOpen && (
        <NewsAudienceDialog post={post} onClose={() => setAudienceOpen(false)} />
      )}
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
    <div className="mt-3 space-y-2 border-t border-glass-border pt-3">
      {error && <p className="text-xs text-red">Не удалось загрузить комментарии.</p>}
      {comments === null && !error && <SkeletonRows rows={2} />}
      {(comments ?? []).map((c) => (
        <div key={c.id} className="rounded-lg bg-surface/60 px-3 py-2">
          <p className="text-xs font-medium text-text2">
            {c.author_name ?? '—'}{' '}
            <span className="font-normal text-text3">{formatWhen(c.created_at)}</span>
          </p>
          <p className="mt-0.5 text-sm text-text">
            {c.deleted_at ? <span className="italic text-text3">Комментарий удалён</span> : c.body}
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
        />
        <Button type="submit" disabled={!text.trim() || send.isPending}>
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

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (!title.trim()) return
            void save.mutateAsync(undefined as never).then(() => {
              toast.success(isNew ? 'Новость создана (черновик)' : 'Сохранено')
              onClose()
            })
          }}
        >
          <DialogHeader>
            <DialogTitle>{isNew ? 'Новая новость' : 'Изменить новость'}</DialogTitle>
            {isNew && (
              <DialogDescription>
                Новость создаётся черновиком — сотрудники увидят её после публикации.
              </DialogDescription>
            )}
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="news-title">Заголовок</Label>
              <Input
                id="news-title"
                autoFocus={isNew}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <Suspense fallback={<SkeletonRows rows={4} />}>
              <RichEditor value={body} onChange={setBody} placeholder="Текст новости…" />
            </Suspense>
            <div className="flex flex-wrap gap-4">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-text">
                <input
                  type="checkbox"
                  checked={allowComments}
                  onChange={(e) => setAllowComments(e.target.checked)}
                  className="h-4 w-4 accent-[#FFB200]"
                />
                Комментарии
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm text-text">
                <input
                  type="checkbox"
                  checked={allowReactions}
                  onChange={(e) => setAllowReactions(e.target.checked)}
                  className="h-4 w-4 accent-[#FFB200]"
                />
                Реакции
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm text-text">
                <input
                  type="checkbox"
                  checked={requiresAck}
                  onChange={(e) => setRequiresAck(e.target.checked)}
                  className="h-4 w-4 accent-[#FFB200]"
                />
                Обязательное ознакомление
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
              Отмена
            </Button>
            <Button type="submit" disabled={!title.trim() || save.isPending}>
              {save.isPending ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function NewsAudienceDialog({ post, onClose }: { post: NewsPost; onClose: () => void }) {
  const [value, setValue] = useState<AudienceValue>({
    is_all: post.audience_id === null,
    rules: [],
  })
  const save = useNewsMutation(() => learnApi.setNewsAudience(post.id, value))
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Кому видна «{post.title}»</DialogTitle>
          {post.audience_id !== null && (
            <DialogDescription>Правила ниже заменят текущие.</DialogDescription>
          )}
        </DialogHeader>
        <AudiencePicker value={value} onChange={setValue} />
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose} disabled={save.isPending}>
            Отмена
          </Button>
          <Button
            type="button"
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
