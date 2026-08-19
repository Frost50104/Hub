import {
  DndContext,
  DragOverlay,
  PointerSensor,
  TouchSensor,
  closestCorners,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { useMemo, useState } from 'react'

import { TaskEmptyState } from '@/components/task/TaskListStates'
import { useLabelAssignments, useLabels } from '@/hooks/useLabels'
import { useProjectSections } from '@/hooks/useProjects'
import { useTasks, useToggleDone, useUpdateTask } from '@/hooks/useTasks'
import { type Label } from '@/lib/labels'
import { activeFilterCount, toListFilters, type TaskViewFilters } from '@/lib/taskFilters'
import { type Task } from '@/lib/tasks'

import { KanbanCard } from './KanbanCard'
import { KanbanColumn, type ColumnDef } from './KanbanColumn'

interface BoardViewProps {
  projectId: string
  /** Эффективное право на правку — считает сервер (Project.can_edit). */
  canEdit: boolean
  onTaskClick: (id: string) => void
  filters?: TaskViewFilters
  /** Сброс фильтров из пустого состояния «под фильтры не попала ни одна». */
  onResetFilters?: () => void
}

/** Лента колонок: одна геометрия для карточек и для скелетона. */
const LANE_CLASS =
  'flex snap-x snap-mandatory items-start gap-3 overflow-x-auto overscroll-x-contain pb-4 md:snap-none'

/**
 * Скелетон доски повторяет раскладку колонок. Без пульсации — то же правило,
 * что в списке: мигание читается как поломка, а не как загрузка.
 */
function BoardSkeleton() {
  return (
    <div className={LANE_CLASS} aria-hidden>
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="flex w-72 shrink-0 flex-col gap-2 p-1">
          <span className="mx-1.5 mb-1 mt-1.5 h-3.5 w-[120px] rounded-[5px] bg-surface" />
          {[78, 96, 84].map((h, j) => (
            <span
              key={j}
              className="block rounded-xl border border-glass-border bg-surface"
              style={{ height: h }}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

const ORPHAN_ID = '__orphan__'

export function BoardView({
  projectId,
  canEdit,
  onTaskClick,
  filters,
  onResetFilters,
}: BoardViewProps) {
  const sections = useProjectSections(projectId)
  // forBoard: доска всегда в position-порядке, иначе ломается drag.
  // При активных фильтрах позиция drag считается между видимыми соседями —
  // допустимый компромисс (так же ведёт себя Asana).
  const listFilters = useMemo(() => toListFilters(filters ?? {}, { forBoard: true }), [filters])
  const tasks = useTasks(projectId, listFilters)
  const update = useUpdateTask(projectId)
  const toggleDone = useToggleDone(projectId)
  const [activeId, setActiveId] = useState<string | null>(null)
  // Колонка-приёмник считается ЗДЕСЬ, а не из useDroppable в самой колонке:
  // карточки — тоже droppable, и closestCorners почти всегда отдаёт id
  // карточки, из-за чего `isOver` у колонки не поднимался и подсветка приёма
  // не появлялась нигде, кроме пустого места под последней карточкой.
  const [overColumnId, setOverColumnId] = useState<string | null>(null)

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

  const activeTask = (tasks.data ?? []).find((t) => t.id === activeId) ?? null

  const onDragStart = (e: DragStartEvent) => {
    setActiveId(String(e.active.id))
  }

  const columnIdFor = (overId: string): string | null => {
    const byId = columns.find((c) => c.dndId === overId)
    if (byId) return byId.dndId
    return columns.find((c) => c.tasks.some((t) => t.id === overId))?.dndId ?? null
  }

  const onDragOver = (e: DragOverEvent) => {
    setOverColumnId(e.over ? columnIdFor(String(e.over.id)) : null)
  }

  const onDragEnd = (e: DragEndEvent) => {
    setActiveId(null)
    setOverColumnId(null)
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

  if (tasks.isLoading || sections.isLoading) return <BoardSkeleton />

  // Пусто / фильтр / ошибка — ОДИН блок на всю область: четыре одинаковых
  // сообщения в колонках читались бы как четыре разные проблемы.
  if (tasks.isError || sections.isError) {
    return (
      <TaskEmptyState
        tone="error"
        title="Не удалось загрузить задачи"
        text="Проверьте соединение и попробуйте ещё раз."
        cta="Повторить"
        onCta={() => {
          if (tasks.isError) void tasks.refetch()
          if (sections.isError) void sections.refetch()
        }}
      />
    )
  }
  const visible = (tasks.data ?? []).filter((t) => !t.parent_task_id)
  if (visible.length === 0) {
    return activeFilterCount(filters ?? {}) > 0 ? (
      <TaskEmptyState
        title="Под фильтры не попала ни одна задача"
        text="Снимите часть условий — или посмотрите список целиком."
        cta="Сбросить фильтры"
        onCta={onResetFilters}
      />
    ) : (
      <TaskEmptyState
        title="Пока нет задач. Создайте первую."
        text="Колонки появятся вместе с первой задачей: доска группирует по секциям."
      />
    )
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={() => {
        setActiveId(null)
        setOverColumnId(null)
      }}
    >
      <div className={LANE_CLASS}>
        {columns.map((col) => (
          <KanbanColumn
            key={col.dndId}
            column={col}
            projectId={projectId}
            canEdit={canEdit}
            isOver={overColumnId === col.dndId}
            childrenByParent={childrenByParent}
            labelsByTask={labelsByTask}
            onTaskClick={onTaskClick}
            onToggleDone={toggleDone}
          />
        ))}
      </div>
      <DragOverlay>
        {activeTask && <KanbanCard task={activeTask} overlay />}
      </DragOverlay>
    </DndContext>
  )
}
