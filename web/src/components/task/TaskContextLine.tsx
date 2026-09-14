import { Link2, ListTree, MessageSquare, Paperclip, Repeat } from 'lucide-react'

import { TaskLabelChip } from '@/components/task/TaskLabelChip'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { describeRecurrence, shortRecurrence } from '@/lib/taskRecurrence'
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

/**
 * Будет ли строке контекста что показать. Один источник истины для самой
 * строки и для списков, которые решают, резервировать ли под неё полосу.
 */
export function hasTaskContext(
  task: Pick<Task, 'comment_count' | 'attachment_count' | 'blocker_count' | 'recurrence'>,
  opts: {
    labels?: Label[]
    subtasks?: SubtaskStats
    fallback?: string | null
    stage?: string | null
    mode?: 'auto' | 'fallback'
  } = {},
): boolean {
  if (opts.fallback) return true
  if (opts.mode === 'fallback') return false
  if (opts.stage) return true
  return (
    !!task.recurrence ||
    (opts.labels?.length ?? 0) > 0 ||
    (opts.subtasks?.total ?? 0) > 0 ||
    (task.comment_count ?? 0) > 0 ||
    (task.attachment_count ?? 0) > 0 ||
    (task.blocker_count ?? 0) > 0
  )
}

interface TaskContextLineProps {
  task: Task
  labels?: Label[]
  subtasks?: SubtaskStats
  /**
   * Имя колонки доски. Единственный признак движения задачи после 0044:
   * состояние схлопнулось в галочку, и без колонки список не отличает
   * «взяли в работу» от «лежит нетронутой».
   */
  stage?: string | null
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
  /**
   * Резервировать полосу 22px, когда показывать нечего. По умолчанию да:
   * в смешанном списке иначе «дышат» заголовки — у строк с контекстом они
   * выше, у пустых по центру. Списки, где контекста нет НИ У ОДНОЙ строки
   * (секция «ЛИЧНОЕ»), передают `false` — иначе заголовок висит выше
   * чекбокса и правых ячеек, которые центрируются по всей строке.
   */
  reserve?: boolean
  className?: string
}

export function TaskContextLine({
  task,
  labels,
  subtasks,
  stage,
  fallback,
  compact = false,
  mode = 'auto',
  reserve = true,
  className,
}: TaskContextLineProps) {
  const shownLabels = compact ? (labels ?? []).slice(0, 1) : (labels ?? [])
  const hiddenLabels = (labels?.length ?? 0) - shownLabels.length
  const hasSubs = !!subtasks && subtasks.total > 0
  const comments = task.comment_count ?? 0
  const files = task.attachment_count ?? 0
  const blocked = (task.blocker_count ?? 0) > 0
  const repeats = task.recurrence ?? null
  const bare =
    mode === 'fallback' ||
    (!stage &&
      shownLabels.length === 0 &&
      !hasSubs &&
      !comments &&
      !files &&
      !blocked &&
      !repeats)

  if (bare && !fallback && !reserve) return null

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
      {mode !== 'fallback' && repeats && (
        <MetaChip icon={Repeat} title={`Повторяется ${describeRecurrence(repeats)}`}>
          {shortRecurrence(repeats)}
        </MetaChip>
      )}
      {mode !== 'fallback' && stage && (
        <span
          className="inline-flex h-[22px] shrink-0 items-center rounded-md bg-surface px-1.5 text-[12px] font-semibold text-text2"
          title={`Колонка: ${stage}`}
        >
          {stage}
        </span>
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
