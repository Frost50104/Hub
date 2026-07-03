import {
  DndContext,
  DragOverlay,
  PointerSensor,
  TouchSensor,
  closestCorners,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { useMemo, useState } from 'react'

import { Skeleton } from '@/components/ui/Skeleton'
import { useLabelAssignments, useLabels } from '@/hooks/useLabels'
import { useProjectSections } from '@/hooks/useProjects'
import { useTasks, useToggleDone, useUpdateTask } from '@/hooks/useTasks'
import { type Label } from '@/lib/labels'
import { type ProjectRole } from '@/lib/projects'
import { toListFilters, type TaskViewFilters } from '@/lib/taskFilters'
import { type Task } from '@/lib/tasks'

import { KanbanCard } from './KanbanCard'
import { KanbanColumn, type ColumnDef } from './KanbanColumn'

interface BoardViewProps {
  projectId: string
  myRole: ProjectRole | null | undefined
  onTaskClick: (id: string) => void
  filters?: TaskViewFilters
}

const ORPHAN_ID = '__orphan__'

export function BoardView({ projectId, myRole, onTaskClick, filters }: BoardViewProps) {
  const sections = useProjectSections(projectId)
  // forBoard: доска всегда в position-порядке, иначе ломается drag.
  // При активных фильтрах позиция drag считается между видимыми соседями —
  // допустимый компромисс (так же ведёт себя Asana).
  const listFilters = useMemo(() => toListFilters(filters ?? {}, { forBoard: true }), [filters])
  const tasks = useTasks(projectId, listFilters)
  const update = useUpdateTask(projectId)
  const toggleDone = useToggleDone(projectId)
  const [activeId, setActiveId] = useState<string | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 200, tolerance: 5 },
    }),
  )

  const labels = useLabels(projectId)
  const labelAssignments = useLabelAssignments(projectId)
  const labelsByTask = useMemo(() => {
    const byId = new Map((labels.data ?? []).map((l) => [l.id, l]))
    const m = new Map<string, Label[]>()
    for (const a of labelAssignments.data ?? []) {
      const l = byId.get(a.label_id)
      if (!l) continue
      const list = m.get(a.task_id) ?? []
      list.push(l)
      m.set(a.task_id, list)
    }
    return m
  }, [labels.data, labelAssignments.data])

  // Счётчик k/N по родителям. При активных фильтрах дети могут быть
  // отфильтрованы — тогда чип занижен/скрыт; полный счёт виден в карточке.
  const childrenByParent = useMemo(() => {
    const m = new Map<string, { total: number; done: number }>()
    for (const t of tasks.data ?? []) {
      if (!t.parent_task_id) continue
      const s = m.get(t.parent_task_id) ?? { total: 0, done: 0 }
      s.total += 1
      if (t.status === 'done') s.done += 1
      m.set(t.parent_task_id, s)
    }
    return m
  }, [tasks.data])

  const columns: ColumnDef[] = useMemo(() => {
    const orphan: Task[] = []
    const map = new Map<string, Task[]>()
    for (const t of tasks.data ?? []) {
      // Подзадачи живут в карточке родителя, а не отдельными карточками.
      if (t.parent_task_id) continue
      if (t.section_id === null) {
        orphan.push(t)
      } else {
        const list = map.get(t.section_id) ?? []
        list.push(t)
        map.set(t.section_id, list)
      }
    }
    const cols: ColumnDef[] = [
      {
        dndId: ORPHAN_ID,
        sectionId: null,
        name: 'Без секции',
        tasks: orphan.sort((a, b) => Number(a.position) - Number(b.position)),
      },
    ]
    for (const s of sections.data ?? []) {
      cols.push({
        dndId: `section-${s.id}`,
        sectionId: s.id,
        name: s.name,
        tasks: (map.get(s.id) ?? []).sort(
          (a, b) => Number(a.position) - Number(b.position),
        ),
      })
    }
    return cols
  }, [tasks.data, sections.data])

  const canEdit = myRole === 'owner' || myRole === 'editor'
  const activeTask = (tasks.data ?? []).find((t) => t.id === activeId) ?? null

  const onDragStart = (e: DragStartEvent) => {
    setActiveId(String(e.active.id))
  }

  const onDragEnd = (e: DragEndEvent) => {
    setActiveId(null)
    if (!e.over) return
    const taskId = String(e.active.id)
    const overId = String(e.over.id)

    const sourceColumn = columns.find((c) => c.tasks.some((t) => t.id === taskId))
    if (!sourceColumn) return

    // overId may be either a column dndId or a task id.
    let targetColumn = columns.find((c) => c.dndId === overId)
    let overTaskIndex: number | undefined
    if (!targetColumn) {
      targetColumn = columns.find((c) => c.tasks.some((t) => t.id === overId))
      overTaskIndex = targetColumn?.tasks.findIndex((t) => t.id === overId)
    }
    if (!targetColumn) return

    // No-op if hovering over the same task without moving anywhere new.
    if (sourceColumn.dndId === targetColumn.dndId && overId === taskId) return

    // Working list = target column tasks WITHOUT the dragged task.
    const targetTasks = targetColumn.tasks.filter((t) => t.id !== taskId)
    let newPosition: number

    if (targetTasks.length === 0) {
      newPosition = 1
    } else if (overTaskIndex === undefined || overId === targetColumn.dndId) {
      // Dropped on column body → append to the tail.
      newPosition = Number(targetTasks[targetTasks.length - 1]!.position) + 1
    } else {
      // Index in the *filtered* list (without the moved task).
      const idxInFiltered = targetTasks.findIndex((t) => t.id === overId)
      const at = targetTasks[idxInFiltered]!
      const before = idxInFiltered > 0 ? targetTasks[idxInFiltered - 1] : undefined
      if (!before) {
        newPosition = Number(at.position) - 1
      } else {
        newPosition = (Number(before.position) + Number(at.position)) / 2
      }
    }

    const sourceTask = sourceColumn.tasks.find((t) => t.id === taskId)!
    const samePosition =
      Math.abs(newPosition - Number(sourceTask.position)) < 1e-6
    const sameSection = sourceColumn.sectionId === targetColumn.sectionId
    if (samePosition && sameSection) return

    update.mutate({
      id: taskId,
      section_id: targetColumn.sectionId,
      position: newPosition,
    })
  }

  if (tasks.isLoading || sections.isLoading) {
    return (
      <div className="flex gap-3 pb-4" aria-hidden>
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="w-72 shrink-0 space-y-2">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ))}
      </div>
    )
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      <div className="flex snap-x snap-mandatory gap-3 overflow-x-auto overscroll-x-contain pb-4 md:snap-none">
        {columns.map((col) => (
          <KanbanColumn
            key={col.dndId}
            column={col}
            projectId={projectId}
            canEdit={canEdit}
            childrenByParent={childrenByParent}
            labelsByTask={labelsByTask}
            onTaskClick={onTaskClick}
            onToggleDone={toggleDone}
          />
        ))}
      </div>
      <DragOverlay>
        {activeTask && <KanbanCard task={activeTask} />}
      </DragOverlay>
    </DndContext>
  )
}
