import { Link2, ListTree, MessageSquare, Paperclip } from 'lucide-react'

import { TaskLabelChip } from '@/components/task/TaskLabelChip'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { type SubtaskStats, type Task } from '@/lib/tasks'

/**
 * Вторая строка строки задачи. Рендерится ВСЕГДА, даже когда меток и подзадач
 * нет: иначе высота строки скачет и список перестаёт сканироваться. Если
 * рассказывать нечего — её занимает название секции (в «Моих задачах» и на
 * «Главной» — название проекта).
 *
 * Счётчики комментариев/вложений/зависимостей приходят с сервера только в
 * списке задач проекта. `undefined` — «не знаем» (чип не рисуем), `0` —
 * «знаем, что нет»: иначе чип мигал бы при каждом оптимистичном обновлении.
 */

function MetaChip({
  icon: Icon,
  children,
  title,
}: {
  icon: typeof ListTree
  children: React.ReactNode
  title: string
}) {
  return (
    <span
      className="inline-flex h-[22px] shrink-0 items-center gap-1 text-[13px] text-text2"
      title={title}
    >
      <Icon className="h-[14px] w-[14px]" strokeWidth={1.9} />
      {children}
    </span>
  )
}

interface TaskContextLineProps {
  task: Task
  labels?: Label[]
  subtasks?: SubtaskStats
  /** Что показать, когда рассказывать нечего: секция или проект. */
  fallback?: string | null
  /** На мобильном по месту влезает одна метка, остальные схлопываются в «+N». */
  compact?: boolean
  /**
   * `fallback` — показывать ТОЛЬКО подпись (проект), без чипов. Нужно узким
   * спискам «Главной»: там проект важнее меток и счётчиков, а места на оба
   * набора нет.
   */
  mode?: 'auto' | 'fallback'
  className?: string
}

export function TaskContextLine({
  task,
  labels,
  subtasks,
  fallback,
  compact = false,
  mode = 'auto',
  className,
}: TaskContextLineProps) {
  const shownLabels = compact ? (labels ?? []).slice(0, 1) : (labels ?? [])
  const hiddenLabels = (labels?.length ?? 0) - shownLabels.length
  const hasSubs = !!subtasks && subtasks.total > 0
  const comments = task.comment_count ?? 0
  const files = task.attachment_count ?? 0
  const blocked = (task.blocker_count ?? 0) > 0
  const bare =
    mode === 'fallback' ||
    (shownLabels.length === 0 && !hasSubs && !comments && !files && !blocked)

  return (
    <span
      className={cn(
        'flex min-w-0 items-center gap-2',
        compact ? 'min-h-[22px] gap-[7px]' : 'h-[22px]',
        className,
      )}
    >
      {bare && fallback && (
        <span className="min-w-0 truncate text-[13px] text-text2">{fallback}</span>
      )}
      {mode !== 'fallback' && compact && hasSubs && (
        <MetaChip icon={ListTree} title={`Подзадачи: ${subtasks!.done} из ${subtasks!.total}`}>
          {subtasks!.done}/{subtasks!.total}
        </MetaChip>
      )}
      {mode !== 'fallback' &&
        shownLabels.map((l) => <TaskLabelChip key={l.id} label={l} />)}
      {mode !== 'fallback' && hiddenLabels > 0 && (
        <span className="inline-flex h-[22px] shrink-0 items-center rounded-md bg-surface px-1.5 text-[12px] font-bold text-text2">
          +{hiddenLabels}
        </span>
      )}
      {!compact && hasSubs && (
        <MetaChip icon={ListTree} title={`Подзадачи: ${subtasks!.done} из ${subtasks!.total}`}>
          {subtasks!.done}/{subtasks!.total}
        </MetaChip>
      )}
      {!compact && comments > 0 && (
        <MetaChip icon={MessageSquare} title={`Комментариев: ${comments}`}>
          {comments}
        </MetaChip>
      )}
      {!compact && files > 0 && (
        <MetaChip icon={Paperclip} title={`Вложений: ${files}`}>
          {files}
        </MetaChip>
      )}
      {!compact && blocked && (
        // Словарь TaskDependencies.tsx: «Зависит от». Слова «Ждёт» в продукте
        // нет, а список, доска и карточка обязаны называть связь одинаково.
        <span className="inline-flex h-[22px] shrink-0 items-center gap-1 rounded-md bg-surface px-[7px] text-[12px] font-semibold text-text2">
          <Link2 className="h-[14px] w-[14px]" strokeWidth={1.9} />
          Зависит от задачи
        </span>
      )}
    </span>
  )
}
