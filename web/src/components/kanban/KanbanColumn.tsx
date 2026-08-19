import { useDroppable } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'

import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { type SubtaskStats, type Task } from '@/lib/tasks'

import { KanbanCard } from './KanbanCard'

export interface ColumnDef {
  /** `null` for the "Без секции" bucket. */
  sectionId: string | null
  /** dnd-kit identifier — must be unique per column. */
  dndId: string
  name: string
  tasks: Task[]
}

interface KanbanColumnProps {
  column: ColumnDef
  projectId: string
  canEdit: boolean
  childrenByParent?: Map<string, SubtaskStats>
  labelsByTask?: Map<string, Label[]>
  onTaskClick: (id: string) => void
  onToggleDone: (task: Task) => void
  /** Колонка под курсором. Считает BoardView: собственный `isOver` droppable'а
   *  почти всегда false — ближайшей целью оказывается карточка, а не колонка. */
  isOver?: boolean
}

/**
 * Колонка доски: 288px (`sm:w-72`), отбивка 4px, радиус 12.
 *
 * Состояние приёма — пунктир `--amber` 50% и фон 5%, БЕЗ сплошной рамки.
 * Мобильная колонка отличается только шириной и `scroll-snap`: раньше она
 * рендерилась отдельным контейнером, и подсветка приёма на телефоне пропадала.
 *
 * Точка в шапке нейтральная: колонка — это секция проекта, а у секции нет
 * статуса. Красить её зелёным нельзя — зелёный означает «сделано».
 */
export function KanbanColumn({
  column,
  projectId,
  canEdit,
  childrenByParent,
  labelsByTask,
  onTaskClick,
  onToggleDone,
  isOver: isOverColumn = false,
}: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id: column.dndId })
  const receiving = isOver || isOverColumn

  return (
    <div
      ref={setNodeRef}
      className={cn(
        'flex w-[85%] max-w-[320px] shrink-0 snap-start flex-col rounded-xl border border-dashed p-1 transition-colors sm:w-72 sm:max-w-none',
        receiving
          ? 'border-amber/50 bg-amber/[0.05]'
          : 'border-transparent bg-transparent',
      )}
    >
      <header className="flex items-center gap-2 px-1.5 pb-2.5 pt-1.5">
        <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-text2" />
        <h3 className="min-w-0 truncate font-display text-[14px] font-bold text-text">
          {column.name}
        </h3>
        <span className="ml-auto font-mono text-[13px] text-text2">
          {column.tasks.length}
        </span>
      </header>

      <div className="flex flex-col gap-2">
        <SortableContext
          items={column.tasks.map((t) => t.id)}
          strategy={verticalListSortingStrategy}
        >
          {column.tasks.map((t) => (
            <KanbanCard
              key={t.id}
              task={t}
              subtasks={childrenByParent?.get(t.id)}
              labels={labelsByTask?.get(t.id)}
              onClick={() => onTaskClick(t.id)}
              onToggleDone={() => onToggleDone(t)}
            />
          ))}
        </SortableContext>

        {column.tasks.length === 0 && (
          // Заголовка нет: продукт говорит «Здесь пока пусто», а не командует.
          <div className="flex flex-col gap-2 rounded-xl border border-dashed border-glass-border px-3.5 py-[18px] text-center">
            <p className="text-[14px] leading-[1.45] text-text2">Здесь пока пусто.</p>
            <p className="text-[13px] leading-[1.45] text-text2">
              Перетащите задачу или создайте новую внизу колонки.
            </p>
          </div>
        )}

        {canEdit && (
          <TaskInlineCreate projectId={projectId} sectionId={column.sectionId} />
        )}
      </div>
    </div>
  )
}
