import { Link2, ListTree, MessageSquare, Paperclip, Repeat } from 'lucide-react'

import { ProjectChip } from '@/components/task/ProjectChip'
import { TaskLabelChip } from '@/components/task/TaskLabelChip'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { hasTaskContext, type TaskContextMode } from '@/lib/taskContext'
import { type TaskProjectLabel } from '@/lib/taskProjectLabel'
import { describeRecurrence, shortRecurrence } from '@/lib/taskRecurrence'
import { type SubtaskStats, type Task } from '@/lib/tasks'

/**
 * Вторая строка строки задачи. Рендерится ВСЕГДА, даже когда меток и подзадач
 * нет: иначе высота строки скачет и список перестаёт сканироваться.
 *
 * Слева — проект чипом-ссылкой (`ProjectChip`), за ним имя колонки текстом и
 * остальные чипы. С 16.09 проект и колонка показываются ВМЕСТЕ: до этого
 * проект приходил пропом `fallback` и рисовался, только если чипов нет
 * вовсе, — а колонка есть почти у каждой рабочей задачи, и на «Моих задачах»
 * имя проекта молча пропадало (ОС владельца: «стоит указывать не только в
 * каком столбце задача, но и в каком проекте»). Роли распределены тем же
 * вечером по второй ОС: «проект выглядит как простой текст, а колонка — как
 * чип; должно быть наоборот, и по чипу должен открываться проект». Решение
 * «что показать» живёт в `lib/taskContext.ts` — одно на строку и на списки,
 * которые резервируют под неё полосу.
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
  /**
   * Имя колонки доски — текстом, не чипом (16.09). Единственный признак
   * движения задачи после 0044: состояние схлопнулось в галочку, и без
   * колонки список не отличает «взяли в работу» от «лежит нетронутой».
   */
  stage?: string | null
  /**
   * Проект — чип-ссылка на его страницу (`lib/taskProjectLabel.ts` знает и
   * подпись, и адрес). Показывается ВСЕГДА, когда передан, и соседствует с
   * колонкой — в обеих раскладках (на десктопе с 16.09: отдельный столбец
   * «Проект» владелец попросил заменить этой же парой). Внутри проекта его не
   * передают — там оно дубль.
   */
  project?: TaskProjectLabel | null
  /** На мобильном по месту влезает одна метка, остальные схлопываются в «+N». */
  compact?: boolean
  /**
   * `plain` — показывать ТОЛЬКО подпись (проект), без чипов. Нужно узким
   * спискам «Главной»: там проект важнее меток и счётчиков, а места на оба
   * набора нет.
   */
  mode?: TaskContextMode
  /**
   * Резервировать полосу 22px, когда показывать нечего. По умолчанию да:
   * в смешанном списке иначе «дышат» заголовки — у строк с контекстом они
   * выше, у пустых по центру. Списки, где контекста нет НИ У ОДНОЙ строки
   * (вкладка «Личные»), передают `false` — иначе заголовок висит выше
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
  project,
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
  // Показывать ли строку вовсе — решает lib; тот же ответ получают списки,
  // резервирующие под неё полосу, поэтому разойтись они не могут.
  const show = hasTaskContext(task, { labels, subtasks, stage, mode, project })

  if (!show && !reserve) return null

  return (
    <span
      className={cn(
        'flex min-w-0 items-center gap-2',
        compact ? 'min-h-[22px] gap-[7px]' : 'h-[22px]',
        className,
      )}
    >
      <ProjectChip
        label={project}
        // Потолок — только когда рядом стоит колонка: чип `shrink-0`, и без
        // потолка длинное имя проекта («ВХОДЯЩИЕ отд. Управления магазинами»)
        // оставляло бы от колонки одну букву. Одинокий чип (plain-режим
        // «Главной») ограничивать нечем — пусть занимает строку.
        className={mode !== 'plain' && stage ? 'max-w-[45%]' : 'max-w-full'}
      />
      {mode !== 'plain' && repeats && (
        <MetaChip icon={Repeat} title={`Повторяется ${describeRecurrence(repeats)}`}>
          {shortRecurrence(repeats)}
        </MetaChip>
      )}
      {mode !== 'plain' && stage && (
        // Текстом, не чипом (16.09): чип — у проекта, он ссылка. Колонка
        // сжимается и обрезается сама — имена бывают в 50 символов, а рядом
        // стоит чип проекта с потолком 45%.
        <span className="min-w-0 truncate text-[13px] text-text2" title={`Колонка: ${stage}`}>
          {stage}
        </span>
      )}
      {mode !== 'plain' && compact && hasSubs && (
        <MetaChip icon={ListTree} title={`Подзадачи: ${subtasks!.done} из ${subtasks!.total}`}>
          {subtasks!.done}/{subtasks!.total}
        </MetaChip>
      )}
      {mode !== 'plain' &&
        shownLabels.map((l) => <TaskLabelChip key={l.id} label={l} />)}
      {mode !== 'plain' && hiddenLabels > 0 && (
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
