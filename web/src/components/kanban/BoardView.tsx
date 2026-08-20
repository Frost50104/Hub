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
import { Plus } from 'lucide-react'
import { useMemo, useState } from 'react'

import { TaskEmptyState } from '@/components/task/TaskListStates'
import { useLabelAssignments, useLabels } from '@/hooks/useLabels'
import { useStages, useUpdateStage } from '@/hooks/useStages'
import { useTasks, useToggleDone, useUpdateTask } from '@/hooks/useTasks'
import { dataAgeLabel } from '@/lib/dates'
import { type Label } from '@/lib/labels'
import { type TaskStage } from '@/lib/stages'
import { activeFilterCount, toListFilters, type TaskViewFilters } from '@/lib/taskFilters'
import { type Task } from '@/lib/tasks'

import { KanbanCard } from './KanbanCard'
import { KanbanColumn, type ColumnDef } from './KanbanColumn'
import { DeleteStageDialog, StageFormDialog } from './StageDialogs'
import { DropdownMenuItem } from '@/components/ui/DropdownMenu'

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
// pb-24 на телефоне: последняя карточка колонки иначе уходит под плавающую
// пилюлю вида и таб-бар (макет: отступ 96px).
const LANE_CLASS =
  'flex snap-x snap-mandatory items-start gap-3 overflow-x-auto overscroll-x-contain pb-24 md:snap-none lg:pb-4'

/**
 * Скелетон доски повторяет раскладку колонок. Без пульсации — то же правило,
 * что в списке: мигание читается как поломка, а не как загрузка.
 */
function BoardSkeleton({ columns = 4 }: { columns?: number }) {
  return (
    <div className={LANE_CLASS} aria-hidden>
      {Array.from({ length: Math.max(1, columns) }, (_, i) => (
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

/**
 * Доска: колонка = ЭТАП задачи (`project_stages`), имена пользовательские,
 * этапов сколько угодно; справа ленту замыкает «+ Этап». Перетаскивание
 * патчит `stage_id` — сервер ставит зеркало `status`, completed_at и
 * позицию в хвост. «Без этапа» появляется только если такие задачи есть
 * (окно деплоя 0040 / SET NULL после удаления этапа).
 */
export function BoardView({
  projectId,
  canEdit,
  onTaskClick,
  filters,
  onResetFilters,
}: BoardViewProps) {
  const stages = useStages(projectId)
  // forBoard: доска всегда в position-порядке, иначе ломается drag.
  // При активных фильтрах позиция drag считается между видимыми соседями —
  // допустимый компромисс (так же ведёт себя Asana).
  const listFilters = useMemo(() => toListFilters(filters ?? {}, { forBoard: true }), [filters])
  const tasks = useTasks(projectId, listFilters)
  const update = useUpdateTask(projectId)
  const updateStage = useUpdateStage(projectId)
  const toggleDone = useToggleDone(projectId)
  const [activeId, setActiveId] = useState<string | null>(null)
  // Колонка-приёмник считается ЗДЕСЬ, а не из useDroppable в самой колонке:
  // карточки — тоже droppable, и closestCorners почти всегда отдаёт id
  // карточки, из-за чего `isOver` у колонки не поднимался и подсветка приёма
  // не появлялась нигде, кроме пустого места под последней карточкой.
  const [overColumnId, setOverColumnId] = useState<string | null>(null)
  const [stageForm, setStageForm] = useState<{ open: boolean; stage: TaskStage | null }>({
    open: false,
    stage: null,
  })
  const [stageDelete, setStageDelete] = useState<TaskStage | null>(null)

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
      if (!t.stage_id) {
        orphan.push(t)
      } else {
        const list = map.get(t.stage_id) ?? []
        list.push(t)
        map.set(t.stage_id, list)
      }
    }
    const byPos = (a: Task, b: Task) => Number(a.position) - Number(b.position)
    const cols: ColumnDef[] = []
    if (orphan.length > 0) {
      cols.push({
        dndId: ORPHAN_ID,
        stage: null,
        name: 'Без этапа',
        tasks: orphan.sort(byPos),
        total: null,
      })
    }
    for (const s of stages.data ?? []) {
      cols.push({
        dndId: `stage-${s.id}`,
        stage: s,
        name: s.name,
        tasks: (map.get(s.id) ?? []).sort(byPos),
        total: s.task_count ?? null,
      })
    }
    return cols
  }, [tasks.data, stages.data])

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
    // В «Без этапа» бросать нельзя — это не этап, а остаток.
    if (!targetColumn.stage) return

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
    const samePosition = Math.abs(newPosition - Number(sourceTask.position)) < 1e-6
    const sameStage = sourceColumn.stage?.id === targetColumn.stage.id
    if (samePosition && sameStage) return

    update.mutate(
      sameStage
        ? { id: taskId, position: newPosition }
        : {
            id: taskId,
            stage_id: targetColumn.stage.id,
            position: newPosition,
            __optimistic: { status: targetColumn.stage.system_status },
          },
    )
  }

  if (tasks.isLoading || stages.isLoading) {
    return <BoardSkeleton columns={stages.data?.length ?? 4} />
  }

  // Пусто / фильтр / ошибка — ОДИН блок на всю область: четыре одинаковых
  // сообщения в колонках читались бы как четыре разные проблемы.
  if (tasks.isError || stages.isError) {
    return (
      <TaskEmptyState
        tone="error"
        title="Не удалось загрузить задачи"
        text="Проверьте соединение и попробуйте ещё раз."
        meta={dataAgeLabel(tasks.dataUpdatedAt)}
        cta="Повторить"
        onCta={() => {
          if (tasks.isError) void tasks.refetch()
          if (stages.isError) void stages.refetch()
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
        text="Доска группирует по этапам: колонки оживут с первой задачей."
      />
    )
  }

  const stageList = stages.data ?? []
  const moveStage = (stage: TaskStage, dir: -1 | 1) => {
    const idx = stageList.findIndex((s) => s.id === stage.id)
    const next = idx + dir
    if (idx < 0 || next < 0 || next >= stageList.length) return
    updateStage.mutate({ stageId: stage.id, position: next })
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
        {columns.map((col, i) => (
          <KanbanColumn
            key={col.dndId}
            quickCreateTarget={i === 0}
            column={col}
            projectId={projectId}
            canEdit={canEdit}
            isOver={overColumnId === col.dndId}
            childrenByParent={childrenByParent}
            labelsByTask={labelsByTask}
            onTaskClick={onTaskClick}
            onToggleDone={toggleDone}
            onRenameStage={(s) => setStageForm({ open: true, stage: s })}
            onDeleteStage={(s) => setStageDelete(s)}
            extraMenu={
              col.stage ? (
                <>
                  <DropdownMenuItem onSelect={() => moveStage(col.stage!, -1)}>Левее</DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => moveStage(col.stage!, 1)}>Правее</DropdownMenuItem>
                </>
              ) : null
            }
          />
        ))}
        {/* «+ Этап» — призрачная колонка той же ширины, что соседи. */}
        {canEdit && (
          <button
            type="button"
            onClick={() => setStageForm({ open: true, stage: null })}
            className="flex min-h-12 w-[85%] max-w-[320px] shrink-0 snap-start items-center justify-center gap-2 rounded-xl border border-dashed border-glass-border text-[14px] font-semibold text-text2 transition-colors hover:border-amber hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 sm:w-72 sm:max-w-none lg:min-h-11"
          >
            <Plus className="h-4 w-4" strokeWidth={2.2} />
            Этап
          </button>
        )}
      </div>
      <DragOverlay>
        {activeTask && <KanbanCard task={activeTask} overlay />}
      </DragOverlay>

      <StageFormDialog
        open={stageForm.open}
        onOpenChange={(v) => setStageForm((s) => ({ ...s, open: v }))}
        projectId={projectId}
        stage={stageForm.stage}
      />
      <DeleteStageDialog
        open={stageDelete !== null}
        onOpenChange={(v) => {
          if (!v) setStageDelete(null)
        }}
        projectId={projectId}
        stage={stageDelete}
        stages={stageList}
        taskCount={stageDelete ? (stageDelete.task_count ?? 0) : 0}
      />
    </DndContext>
  )
}
