import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, MessageSquarePlus, Send, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { Button } from '@/components/ui/Button'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import { learnApi, type AiMessage, type AiSource } from '@/lib/learn'

/**
 * AI-помощник (Ф6): RAG-чат по базе знаний компании. Ассистент видит только
 * published-контент аудитории сотрудника; ответы приходят с источниками.
 * Без настроенного провайдера показывается плашка (503 от /ask).
 */

function SourceChips({ sources }: { sources: AiSource[] | null }) {
  if (!sources?.length) return null
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {sources.map((s, i) => (
        <Link
          key={i}
          to={s.url_path}
          className="inline-flex items-center gap-1 rounded-full border border-amber/40 bg-amber/5 px-2 py-0.5 text-[11px] text-amber hover:opacity-80"
        >
          [{i + 1}] {s.title.length > 40 ? `${s.title.slice(0, 40)}…` : s.title}
        </Link>
      ))}
    </div>
  )
}

function Bubble({ message }: { message: Pick<AiMessage, 'role' | 'content' | 'sources'> }) {
  const isUser = message.role === 'user'
  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[85%] rounded-2xl px-3.5 py-2 text-sm',
          isUser
            ? 'rounded-br-sm bg-amber/15 text-text'
            : 'rounded-bl-sm border border-glass-border bg-glass text-text',
        )}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        {!isUser && <SourceChips sources={message.sources} />}
      </div>
    </div>
  )
}

export function LearnAssistantPage() {
  const isDesktop = useIsDesktop()
  const qc = useQueryClient()
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const status = useQuery({ queryKey: ['learn-ai-status'], queryFn: learnApi.aiStatus })
  const conversations = useQuery({
    queryKey: ['learn-ai-conversations'],
    queryFn: learnApi.aiConversations,
    enabled: status.data?.configured === true,
  })
  const messages = useQuery({
    queryKey: ['learn-ai-messages', conversationId],
    queryFn: () => learnApi.aiMessages(conversationId!),
    enabled: Boolean(conversationId),
  })

  const ask = useMutation({
    mutationFn: (question: string) => learnApi.aiAsk(question, conversationId),
    meta: { suppressGlobalError: true },
    onSuccess: (resp) => {
      setConversationId(resp.conversation_id)
      setPendingQuestion(null)
      void qc.invalidateQueries({ queryKey: ['learn-ai-messages', resp.conversation_id] })
      void qc.invalidateQueries({ queryKey: ['learn-ai-conversations'] })
    },
    onError: (e) => {
      setPendingQuestion(null)
      toast.error('Помощник не ответил', { description: extractErrorDetail(e) })
    },
  })

  const removeConversation = useMutation({
    mutationFn: (id: string) => learnApi.aiDeleteConversation(id),
    onSuccess: (_data, id) => {
      if (conversationId === id) setConversationId(null)
      void qc.invalidateQueries({ queryKey: ['learn-ai-conversations'] })
    },
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.data, pendingQuestion])

  const submit = () => {
    const question = draft.trim()
    if (question.length < 3 || ask.isPending) return
    setDraft('')
    setPendingQuestion(question)
    ask.mutate(question)
  }

  if (status.data && !status.data.configured) {
    return (
      <div className="mx-auto max-w-3xl">
        {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="AI-помощник" />}
        <div className="p-4 lg:p-8">
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <Bot className="mx-auto h-10 w-10 text-text3" />
            <p className="mt-3 font-display text-lg font-semibold text-text">
              AI-помощник ещё не подключён
            </p>
            <p className="mx-auto mt-1 max-w-md text-sm text-text2">
              Администратору нужно задать ключ AI-провайдера (YandexGPT, GigaChat
              или OpenAI-совместимый) в настройках сервера — после этого помощник
              начнёт отвечать по базе знаний компании.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-2rem)] max-w-5xl flex-col lg:h-[calc(100vh-3rem)]">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="AI-помощник" />}
      <div className="flex min-h-0 flex-1 gap-4 p-4 lg:p-8">
        {/* Диалоги (desktop) */}
        {isDesktop && (
          <aside className="w-64 shrink-0 space-y-2 overflow-y-auto">
            <Button
              size="sm"
              variant="secondary"
              className="w-full"
              onClick={() => setConversationId(null)}
            >
              <MessageSquarePlus className="h-4 w-4" /> Новый диалог
            </Button>
            {(conversations.data ?? []).map((c) => (
              <div
                key={c.id}
                className={cn(
                  'group flex items-center gap-1 rounded-lg border px-2.5 py-2',
                  conversationId === c.id
                    ? 'border-amber/60 bg-amber/5'
                    : 'border-glass-border bg-glass hover:border-amber/40',
                )}
              >
                <button
                  type="button"
                  onClick={() => setConversationId(c.id)}
                  className="min-w-0 flex-1 truncate text-left text-xs text-text"
                >
                  {c.title}
                </button>
                <button
                  type="button"
                  aria-label="Удалить диалог"
                  onClick={() => void removeConversation.mutateAsync(c.id)}
                  className="rounded p-1 text-text3 opacity-0 hover:text-red group-hover:opacity-100"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </aside>
        )}

        {/* Чат */}
        <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-glass-border bg-glass">
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {!conversationId && !pendingQuestion && (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <Sparkles className="h-8 w-8 text-amber" />
                <p className="mt-3 text-sm font-medium text-text">
                  Спросите о стандартах, товарах или регламентах
                </p>
                <p className="mt-1 max-w-sm text-xs text-text3">
                  Помощник отвечает по базе знаний компании и даёт ссылки на
                  источники. Например: «Как приветствовать гостя в час пик?»
                </p>
              </div>
            )}
            {messages.isLoading && conversationId && <SkeletonRows rows={3} />}
            {(messages.data ?? []).map((m) => (
              <Bubble key={m.id} message={m} />
            ))}
            {pendingQuestion && (
              <>
                <Bubble message={{ role: 'user', content: pendingQuestion, sources: null }} />
                <div className="flex justify-start">
                  <div className="rounded-2xl rounded-bl-sm border border-glass-border bg-glass px-3.5 py-2 text-sm text-text3">
                    Ищу в базе знаний…
                  </div>
                </div>
              </>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="border-t border-glass-border p-3">
            <div className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    submit()
                  }
                }}
                rows={2}
                placeholder="Ваш вопрос… (Enter — отправить)"
                className="flex-1 resize-none rounded-lg border border-glass-border bg-surface px-3 py-2 text-sm text-text placeholder:text-text3 focus-visible:border-amber focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber"
              />
              <Button
                size="icon"
                disabled={draft.trim().length < 3 || ask.isPending}
                onClick={submit}
                aria-label="Отправить"
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
