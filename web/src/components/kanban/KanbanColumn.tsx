import { useDroppable } from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'

import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import { cn } from '@/lib/cn'
import { type Task } from '@/lib/tasks'

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
  onTaskClick: (id: string) => void
  onToggleDone: (task: Task) => void
}

export function KanbanColumn({
  column,
  projectId,
  canEdit,
  onTaskClick,
  onToggleDone,
}: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id: column.dndId })

  return (
    <div className="flex w-72 shrink-0 flex-col gap-2">
      <header className="flex items-center justify-between px-1">
        <h3 className="font-display text-sm font-semibold text-text">{column.name}</h3>
        <span className="text-xs text-text3">{column.tasks.length}</span>
      </header>

      <div
        ref={setNodeRef}
        className={cn(
          'flex min-h-[40vh] flex-col gap-2 rounded-lg border border-dashed border-transparent p-1 transition-colors',
          isOver && 'border-amber/50 bg-amber/5',
        )}
      >
        <SortableContext
          items={column.tasks.map((t) => t.id)}
          strategy={verticalListSortingStrategy}
        >
          {column.tasks.map((t) => (
            <KanbanCard
              key={t.id}
              task={t}
              onClick={() => onTaskClick(t.id)}
              onToggleDone={() => onToggleDone(t)}
            />
          ))}
        </SortableContext>
        {canEdit && (
          <TaskInlineCreate projectId={projectId} sectionId={column.sectionId} />
        )}
      </div>
    </div>
  )
}
