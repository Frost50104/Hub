import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart3, Bot, MessageSquarePlus, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import {
  DeniedBlock,
  ErrorBlock,
  ReportBlock,
  SummaryBlock,
} from '@/components/assistant/Blocks'
import { Composer } from '@/components/assistant/Composer'
import { EmptyState } from '@/components/assistant/EmptyState'
import { PlanCard } from '@/components/assistant/PlanCard'
import { ReportView } from '@/components/assistant/ReportView'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { Markdown } from '@/components/Markdown'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import { plural } from '@/lib/typography'
import {
  assistantApi,
  TURN_LABEL,
  turnTime,
  type AssistantMessage,
  type ReportKind,
} from '@/lib/assistant'

/**
 * Ассистент — ЖУРНАЛ ОПЕРАЦИЙ, а не чат.
 *
 * Разница не косметическая: у чата единица — реплика, у журнала — оборот
 * «команда → что произошло». Поэтому команда сотрудника набирается крупно и
 * играет роль заголовка, а ответ несёт вид (`kind`) и свой блок. Пузырей нет
 * вовсе: ассистент здесь исполнитель, а не собеседник.
 */

function Eyebrow({ message }: { message: AssistantMessage }) {
  return (
    <p className="m-0 text-[12px] font-bold uppercase tracking-[0.08em] text-text2">
      {turnTime(message.created_at)} · {TURN_LABEL[message.kind] ?? 'ответ'}
    </p>
  )
}

/** Один оборот: команда сверху, под ней ответ и блок. */
function Turn({
  question,
  answer,
  conversationId,
  isLast,
  onRetry,
  onExpandReport,
}: {
  question: AssistantMessage
  answer: AssistantMessage | null
  conversationId: string
  isLast: boolean
  onRetry: (text: string) => void
  onExpandReport: (kind: ReportKind) => void
}) {
  const kind = answer?.kind ?? 'answer'
  return (
    <article
      className={cn(
        'flex flex-col gap-[9px] pb-[22px]',
        !isLast && 'mb-[22px] border-b border-hair',
      )}
    >
      {answer && <Eyebrow message={answer} />}
      <h2 className="m-0 font-display text-[17px] font-bold leading-[1.3] text-text lg:text-[20px]">
        {question.content}
      </h2>

      {!answer && (
        <p className="m-0 text-[15px] text-text2 lg:text-[16px]">Собираю ответ…</p>
      )}

      {answer && answer.content && kind !== 'error' && (
        <div className="max-w-[760px] text-[15px] leading-[1.55] text-text2 lg:text-[16px]">
          <Markdown text={answer.content} />
        </div>
      )}

      {kind === 'summary' && answer?.data?.lines && (
        <SummaryBlock lines={answer.data.lines} />
      )}
      {kind === 'action' && answer?.data?.plan && (
        <PlanCard plan={answer.data.plan} conversationId={conversationId} />
      )}
      {kind === 'report' && answer?.data?.report && (
        <ReportBlock report={answer.data.report} onExpand={onExpandReport} />
      )}
      {kind === 'denied' && answer?.data && <DeniedBlock data={answer.data} />}
      {kind === 'error' && answer && (
        <ErrorBlock content={answer.content} onRetry={() => onRetry(question.content)} />
      )}

      {answer?.sources?.length ? (
        <div className="flex flex-wrap gap-2">
          {answer.sources.map((s, i) => (
            <Link
              key={`${s.url_path}-${i}`}
              to={s.url_path}
              className="inline-flex min-h-[34px] items-center rounded-full border border-glass-border px-3 text-[13px] font-medium text-text2 hover:border-amber/40 hover:text-text"
            >
              [{i + 1}] {s.title.length > 44 ? `${s.title.slice(0, 44)}…` : s.title}
            </Link>
          ))}
        </div>
      ) : null}
    </article>
  )
}

/** Сообщения приходят плоским списком — сшиваем в обороты «вопрос+ответ». */
function toTurns(messages: AssistantMessage[]) {
  const turns: { question: AssistantMessage; answer: AssistantMessage | null }[] = []
  for (const m of messages) {
    if (m.role === 'user') turns.push({ question: m, answer: null })
    else if (turns.length) turns[turns.length - 1]!.answer = m
  }
  return turns
}

function NotConfigured({ isAdmin }: { isAdmin: boolean }) {
  return (
    <div className="rounded-[14px] border border-glass-border bg-tint p-8 text-center">
      <Bot className="mx-auto h-10 w-10 text-text3" />
      <p className="mt-3 font-display text-lg font-semibold text-text">
        Ассистент ещё не подключён
      </p>
      <p className="mx-auto mt-1.5 max-w-md text-[15px] leading-[1.5] text-text2">
        Администратору нужно задать ключ AI-провайдера (YandexGPT, GigaChat или
        OpenAI-совместимый) в настройках сервера — после этого ассистент начнёт
        отвечать и выполнять действия.
      </p>
      {isAdmin && (
        <Link
          to="/settings"
          className="mt-4 inline-block text-[14px] font-semibold text-amber hover:opacity-80"
        >
          Открыть настройки →
        </Link>
      )}
    </div>
  )
}

export function AssistantPage() {
  const isDesktop = useIsDesktop()
  const me = useMe()
  const qc = useQueryClient()
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const [view, setView] = useState<'journal' | 'reports'>('journal')
  const [reportKind, setReportKind] = useState<ReportKind>('revenue')
  const bottomRef = useRef<HTMLDivElement>(null)

  const expandReport = (kind: ReportKind) => {
    setReportKind(kind)
    setView('reports')
  }

  const status = useQuery({ queryKey: ['assistant-status'], queryFn: assistantApi.status })
  const conversations = useQuery({
    queryKey: ['assistant-conversations'],
    queryFn: assistantApi.conversations,
    enabled: status.data?.configured === true,
  })
  const messages = useQuery({
    queryKey: ['assistant-messages', conversationId],
    queryFn: () => assistantApi.messages(conversationId!),
    enabled: Boolean(conversationId),
  })

  const ask = useMutation({
    mutationFn: (question: string) => assistantApi.ask(question, conversationId),
    meta: { suppressGlobalError: true },
    onSuccess: (turn) => {
      setConversationId(turn.conversation_id)
      setPending(null)
      void qc.invalidateQueries({ queryKey: ['assistant-messages', turn.conversation_id] })
      void qc.invalidateQueries({ queryKey: ['assistant-conversations'] })
    },
    onError: (e) => {
      setPending(null)
      toast.error('Ассистент не ответил', { description: extractErrorDetail(e) })
    },
  })

  const removeConversation = useMutation({
    mutationFn: (id: string) => assistantApi.deleteConversation(id),
    onSuccess: (_d, id) => {
      if (conversationId === id) setConversationId(null)
      void qc.invalidateQueries({ queryKey: ['assistant-conversations'] })
    },
  })

  useEffect(() => {
    if (view === 'journal') bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.data, pending, view])

  // Переключение вида — в начало. На мобильном скроллится документ, и без
  // сброса экран отчётов открывался прокрученным на позицию журнала.
  // Хелпера useScrollProgress тут не нужно: на десктопе прокручивается
  // внутренний контейнер, который при смене вида монтируется заново.
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [view])

  const submit = (text?: string) => {
    const question = (text ?? draft).trim()
    if (question.length < 3 || ask.isPending) return
    setDraft('')
    setPending(question)
    ask.mutate(question)
  }

  const turns = toTurns(messages.data ?? [])
  const empty = !conversationId && !pending
  // Регистр задаём здесь: шапка его не трогает (preserveEyebrowCase).
  const opCount = empty
    ? 'Новый разговор'
    : `Сегодня, ${turns.length} ${plural(turns.length, 'операция', 'операции', 'операций')}`

  if (status.data && !status.data.configured) {
    return (
      <div className="mx-auto max-w-3xl">
        {!isDesktop && <MobilePageHeader eyebrow="Hub" title="Ассистент" />}
        <div className="p-4 lg:p-8">
          <NotConfigured isAdmin={me.data?.hub_role === 'admin'} />
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-2rem)] max-w-6xl flex-col lg:h-[calc(100vh-3rem)]">
      {!isDesktop && (
        <MobilePageHeader
          eyebrow={view === 'reports' ? 'Отчёты iiko' : opCount}
          preserveEyebrowCase
          title="Ассистент"
          // Вход в отчёты обязан быть и на мобильном: Sidebar рендерится
          // только от 1024px, и без этой кнопки экран отчётов был бы
          // недостижим с телефона — то есть у большинства сотрудников.
          trailing={
            <Button
              size="sm"
              variant={view === 'reports' ? 'default' : 'secondary'}
              onClick={() => setView(view === 'reports' ? 'journal' : 'reports')}
            >
              <BarChart3 className="h-4 w-4" />
              {view === 'reports' ? 'Журнал' : 'Отчёты'}
            </Button>
          }
        />
      )}
      <div className="flex min-h-0 flex-1 gap-6 p-4 lg:p-8">
        {isDesktop && (
          <aside className="w-60 shrink-0 space-y-2 overflow-y-auto">
            <Button
              size="sm"
              variant="secondary"
              className="w-full"
              onClick={() => {
                setConversationId(null)
                setView('journal')
              }}
            >
              <MessageSquarePlus className="h-4 w-4" /> Новый разговор
            </Button>
            <Button
              size="sm"
              variant={view === 'reports' ? 'default' : 'ghost'}
              className="w-full justify-start"
              onClick={() => setView(view === 'reports' ? 'journal' : 'reports')}
            >
              <BarChart3 className="h-4 w-4" /> Отчёты iiko
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
                  className="min-w-0 flex-1 truncate text-left text-[13px] text-text"
                >
                  {c.title}
                </button>
                <button
                  type="button"
                  aria-label="Удалить разговор"
                  onClick={() => removeConversation.mutate(c.id)}
                  className="rounded p-1 text-text3 opacity-0 hover:text-red group-hover:opacity-100"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </aside>
        )}

        {/* min-w-0 обязателен: у flex-элемента min-width по умолчанию auto,
            и колонка отказывалась сжиматься под содержимое отчёта — вкладки
            и списки раздвигали страницу за правый край. */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
          {view === 'reports' ? (
            <div className="min-h-0 flex-1 overflow-y-auto">
              <ReportView initialKind={reportKind} onBack={() => setView('journal')} />
            </div>
          ) : (
          <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {empty && (
              <EmptyState
                canAct={status.data?.can_act ?? false}
                onPick={(text) => submit(text)}
              />
            )}
            {messages.isLoading && conversationId && <SkeletonRows rows={4} />}
            {messages.isError && (
              <QueryError onRetry={() => void messages.refetch()} />
            )}
            {turns.map((t, i) => (
              <Turn
                key={t.question.id}
                question={t.question}
                answer={t.answer}
                conversationId={conversationId!}
                isLast={i === turns.length - 1 && !pending}
                onRetry={(text) => submit(text)}
                onExpandReport={expandReport}
              />
            ))}
            {pending && (
              <article className="flex flex-col gap-[9px] pb-2">
                <h2 className="m-0 font-display text-[17px] font-bold leading-[1.3] text-text lg:text-[20px]">
                  {pending}
                </h2>
                <p className="m-0 text-[15px] text-text2 lg:text-[16px]">
                  Собираю ответ…
                </p>
              </article>
            )}
            <div ref={bottomRef} />
          </div>

          <Composer
            value={draft}
            onChange={setDraft}
            onSubmit={() => submit()}
            busy={ask.isPending}
            showHints={!empty}
            voice={status.data?.voice ?? false}
          />
          </>
          )}
        </div>
      </div>
    </div>
  )
}
