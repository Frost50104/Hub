import { useDroppable } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { MoreHorizontal } from 'lucide-react'
import { type ReactNode } from 'react'

import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { type TaskStage } from '@/lib/stages'
import { type SubtaskStats, type Task } from '@/lib/tasks'

import { KanbanCard } from './KanbanCard'

export interface ColumnDef {
  /** Этап колонки; `null` — «Без этапа» (задачи из окна деплоя 0040). */
  stage: TaskStage | null
  /** dnd-kit identifier — must be unique per column. */
  dndId: string
  name: string
  tasks: Task[]
  /** Тотал по этапу с сервера — правая часть «N из M». */
  total: number | null
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
  /** Первая колонка принимает фокус от «Новая задача» в сайдбаре. */
  quickCreateTarget?: boolean
  /** Меню этапа («…»): переименовать / удалить. Только при canEdit и у настоящего этапа. */
  onRenameStage?: (stage: TaskStage) => void
  onDeleteStage?: (stage: TaskStage) => void
  /** Дополнительные пункты меню (перестановка). */
  extraMenu?: ReactNode
}

/**
 * Колонка доски = ЭТАП задачи: 288px (`sm:w-72`), отбивка 4px, радиус 12.
 * Имя колонки — пользовательское, 14/600 обычным шрифтом, без точки и без
 * цветовой кодировки: цвет принадлежит приоритету и просрочке, а не этапу.
 * Счётчик — «N из M»: слева отрисовано (фильтры могли сузить), справа
 * тотал по этапу с сервера.
 *
 * Состояние приёма — пунктир `--amber` 50% и фон 5%, БЕЗ сплошной рамки.
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
  quickCreateTarget = false,
  onRenameStage,
  onDeleteStage,
  extraMenu,
}: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id: column.dndId })
  const receiving = isOver || isOverColumn
  const shown = column.tasks.length
  const counter =
    column.total != null && column.total !== shown ? `${shown} из ${column.total}` : String(shown)

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
        <h3 className="min-w-0 truncate font-body text-[14px] font-semibold text-text">
          {column.name}
        </h3>
        <span className="ml-auto shrink-0 font-mono text-[13px] text-text2">{counter}</span>
        {canEdit && column.stage && (onRenameStage || onDeleteStage) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={`Действия с этапом «${column.name}»`}
                className="-my-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {onRenameStage && (
                <DropdownMenuItem onSelect={() => onRenameStage(column.stage!)}>
                  Переименовать / статус
                </DropdownMenuItem>
              )}
              {extraMenu}
              {onDeleteStage && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem destructive onSelect={() => onDeleteStage(column.stage!)}>
                    Удалить этап
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
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

        {canEdit && column.stage && (
          <TaskInlineCreate
            projectId={projectId}
            sectionId={null}
            stageId={column.stage.id}
            quickCreateTarget={quickCreateTarget}
          />
        )}
      </div>
    </div>
  )
}
