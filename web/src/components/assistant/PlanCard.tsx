import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { toast } from 'sonner'

import { PlanEditDialog } from './PlanEditDialog'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import { assistantApi, type Plan } from '@/lib/assistant'

/**
 * Карточка плана — ЕДИНСТВЕННЫЙ блок журнала с амбер-рамкой (спека: она
 * требует решения, остальные только сообщают).
 *
 * Порог подтверждения: правка одной задачи выполняется сразу и сюда не
 * попадает; создание, комментарий, архивация и массовые изменения — только
 * через эту карточку. Отмены после «Выполнить» нет, поэтому подпись под
 * кнопками — не украшение, а обещание продукта.
 */

const PRIORITY_LABEL: Record<string, string> = {
  low: 'Низкий',
  medium: 'Обычный',
  high: 'Высокий',
  urgent: 'Срочный',
}

function FieldValue({ field }: { field: Plan['fields'][number] }) {
  if (field.chip === 'key' && field.chip_text) {
    return (
      <span className="flex min-w-0 items-center gap-2">
        <span className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-md bg-amber text-[12px] font-bold uppercase text-on-amber">
          {field.chip_text.slice(0, 2)}
        </span>
        <span className="truncate text-[15px] text-text">{field.value}</span>
      </span>
    )
  }
  if (field.chip === 'priority' && field.chip_text) {
    return (
      <Badge variant={field.chip_text === 'urgent' ? 'destructive' : 'secondary'}>
        {PRIORITY_LABEL[field.chip_text] ?? field.value}
      </Badge>
    )
  }
  if (field.chip === 'who') {
    return (
      <span className="flex min-w-0 items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface text-[12px] font-bold text-text">
          {field.value.slice(0, 1).toUpperCase()}
        </span>
        <span className="truncate text-[15px] text-text">{field.value}</span>
      </span>
    )
  }
  return <span className="block text-[15px] leading-[1.4] text-text">{field.value}</span>
}

function StepDot({ state }: { state: Plan['steps'][number]['state'] }) {
  return (
    <span
      className={cn(
        'mt-[6px] block h-[9px] w-[9px] shrink-0 rounded-full',
        state === 'done' ? 'bg-green' : state === 'now' ? 'bg-amber' : 'bg-text3',
      )}
    />
  )
}

export function PlanCard({
  plan,
  conversationId,
}: {
  plan: Plan
  conversationId: string
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const invalidate = () =>
    void qc.invalidateQueries({ queryKey: ['assistant-messages', conversationId] })

  const execute = useMutation({
    mutationFn: () => assistantApi.executePlan(plan.id),
    meta: { suppressGlobalError: true },
    onSuccess: invalidate,
    onError: (e) =>
      toast.error('Не удалось выполнить', { description: extractErrorDetail(e) }),
  })
  const reject = useMutation({
    mutationFn: () => assistantApi.rejectPlan(plan.id),
    onSuccess: invalidate,
  })

  const pending = plan.status === 'pending'
  const busy = execute.isPending || reject.isPending
  const title = execute.isPending
    ? 'Выполняю…'
    : plan.status === 'done'
      ? 'Выполнено'
      : plan.status === 'rejected'
        ? 'Отклонено'
        : plan.status === 'failed'
          ? 'Не выполнено'
          : plan.title

  return (
    <div
      className={cn(
        // flex-shrink-0 обязателен: в мобильной прокручиваемой колонке
        // браузер сжимает карточку, и её собственный overflow-hidden срезает
        // последнюю строку — прокрутить нечего, контент «уложился».
        'shrink-0 overflow-hidden rounded-[14px] border bg-tint',
        pending || execute.isPending ? 'border-amber/45' : 'border-glass-border',
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-hair px-4 py-3">
        <span
          className={cn(
            'block h-[9px] w-[9px] shrink-0 rounded-full',
            plan.status === 'done' ? 'bg-green' : 'bg-amber',
          )}
        />
        <p className="font-display text-[15px] font-semibold text-text">{title}</p>
        {plan.scope && (
          <span className="ml-auto inline-flex h-[22px] shrink-0 items-center rounded-md border border-hair px-2 text-[12px] font-semibold text-text2">
            {plan.scope}
          </span>
        )}
      </div>

      <dl className="grid grid-cols-1 sm:grid-cols-2">
        {plan.fields.map((field, i) => (
          <div
            key={field.label}
            className={cn(
              'min-w-0 px-4 py-[11px]',
              i > 1 && 'border-t border-hair',
              i === 1 && 'border-t border-hair sm:border-t-0',
              i % 2 === 0 && 'sm:border-r sm:border-hair',
            )}
          >
            <dt className="text-[13px] text-text2">{field.label}</dt>
            <dd className="mt-1 min-w-0">
              <FieldValue field={field} />
            </dd>
          </div>
        ))}
      </dl>

      {plan.steps.length > 0 && pending && (
        <ul className="space-y-2 border-t border-hair px-4 py-3">
          {plan.steps.map((step) => (
            <li key={step.text} className="flex items-start gap-2.5">
              <StepDot state={step.state} />
              <span
                className={cn(
                  'text-[15px] leading-[1.45]',
                  step.state === 'wait' ? 'text-text2' : 'text-text',
                )}
              >
                {step.text}
              </span>
            </li>
          ))}
        </ul>
      )}

      {pending && (
        <div className="border-t border-hair px-4 py-3.5">
          <div className="flex flex-wrap gap-2">
            <Button size="md" disabled={busy} onClick={() => execute.mutate()}>
              {execute.isPending ? 'Выполняю…' : 'Выполнить'}
            </Button>
            <Button
              size="md"
              variant="secondary"
              disabled={busy}
              onClick={() => setEditing(true)}
            >
              Изменить поля
            </Button>
            <Button
              size="md"
              variant="ghost"
              disabled={busy}
              onClick={() => reject.mutate()}
            >
              Отклонить
            </Button>
          </div>
          <p className="mt-2.5 text-[13px] leading-[1.45] text-text2">
            Ничего не изменится, пока вы не нажали «Выполнить»
          </p>
        </div>
      )}

      {plan.status === 'done' && plan.result && (
        <div className="border-t border-hair px-4 py-3.5">
          <p className="text-[15px] font-semibold text-text">{plan.result.text}</p>
          {plan.result.url && (
            <Link
              to={plan.result.url}
              className="mt-1 inline-block text-[14px] font-semibold text-amber hover:opacity-80"
            >
              {plan.result.link_text ?? 'Открыть →'}
            </Link>
          )}
          <p className="mt-2 text-[13px] text-text2">
            Правки — в трекере, как для любой задачи
          </p>
        </div>
      )}

      {plan.status === 'failed' && plan.error && (
        <p className="border-t border-hair px-4 py-3 text-[13px] leading-[1.45] text-red">
          {plan.error}
        </p>
      )}

      {editing && (
        <PlanEditDialog
          plan={plan}
          conversationId={conversationId}
          onClose={() => setEditing(false)}
        />
      )}
    </div>
  )
}
