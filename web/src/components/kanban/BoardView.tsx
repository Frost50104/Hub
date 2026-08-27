import {
  DndContext,
  DragOverlay,
  PointerSensor,
  TouchSensor,
  closestCenter,
  closestCorners,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy } from '@dnd-kit/sortable'
import { Plus } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'

import { TaskEmptyState } from '@/components/task/TaskListStates'
import { useLabelAssignments, useLabels } from '@/hooks/useLabels'
import { useIsTouch } from '@/hooks/useMediaQuery'
import { useStages, useUpdateStage } from '@/hooks/useStages'
import { useTasks, useToggleDone, useUpdateTask } from '@/hooks/useTasks'
import { dataAgeLabel } from '@/lib/dates'
import { type Label } from '@/lib/labels'
import { type TaskStage } from '@/lib/stages'
import { boardHint } from '@/lib/boardHints'
import { reorderStages } from '@/lib/stageOrder'
import { activeFilterCount, toListFilters, type TaskViewFilters } from '@/lib/taskFilters'
import { type Task } from '@/lib/tasks'

import { KanbanCard } from './KanbanCard'
import { KanbanColumn, type ColumnDef } from './KanbanColumn'
import { DeleteStageDialog, StageFormDialog } from './StageDialogs'
import { DropdownMenuItem, DropdownMenuSeparator } from '@/components/ui/DropdownMenu'

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
 * «+ Колонка» — призрачная колонка той же ширины, что соседи.
 *
 * Один компонент на два места: она замыкает ленту справа И стоит на месте
 * первой колонки в проекте, где колонок ещё нет. Две копии разъехались бы по
 * стилям на первой же правке.
 */
function AddStageButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-12 w-[85%] max-w-[320px] shrink-0 snap-start items-center justify-center gap-2 rounded-xl border border-dashed border-glass-border text-[14px] font-semibold text-text2 transition-colors hover:border-amber hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 sm:w-72 sm:max-w-none lg:min-h-11"
    >
      <Plus className="h-4 w-4" strokeWidth={2.2} />
      Колонка
    </button>
  )
}

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

/**
 * Доска: колонка = `project_stages`, имена пользовательские, колонок сколько
 * угодно; справа ленту замыкает «+ Колонка». Перетаскивание карточки патчит
 * `stage_id` — сервер меняет колонку и позицию в хвост, состояние задачи
 * (`done`) при этом НЕ трогается (0044). Перетаскивание КОЛОНКИ патчит её
 * `position`; тип перетаскиваемого различается по `active.data.type`.
 *
 * Доска показывает ТОЛЬКО задачи с колонкой. Задача с `stage_id === null`
 * (прочерк в поле «Колонка», 0046) сюда не попадает вовсе — она живёт в
 * списке, календаре и поиске; их число называет строка над лентой
 * (`lib/boardHints.ts`). Бакета «Без колонки» нет: пустой `stage_id` —
 * легальное состояние, отдельный столбец под него был бы вторым списком.
 *
 * **Колонки видно всегда, если они есть** (решение владельца 26.08). Прежде
 * доска, где ни одна задача не разложена, пряталась целиком — и человек,
 * создавший колонку в новом проекте, не видел её до первой разложенной задачи.
 * Пустое состояние осталось ровно одно: колонок нет вовсе.
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
  // Что именно в руках: в одной ленте тащат и карточки, и колонки. Тип берём у
  // dnd-kit (`data.type`), а не по форме id — правило должно быть видимым.
  const [activeType, setActiveType] = useState<'task' | 'column' | null>(null)
  // Колонка-приёмник считается ЗДЕСЬ, а не из useDroppable в самой колонке:
  // карточки — тоже droppable, и closestCorners почти всегда отдаёт id
  // карточки, из-за чего `isOver` у колонки не поднимался и подсветка приёма
  // не появлялась нигде, кроме пустого места под последней карточкой.
  const [overColumnId, setOverColumnId] = useState<string | null>(null)
  // Диалог остался ТОЛЬКО на создание: имя правится прямо в заголовке колонки.
  const [newStageOpen, setNewStageOpen] = useState(false)
  const [stageDelete, setStageDelete] = useState<TaskStage | null>(null)

  // Перетаскивание — редакторское действие: PATCH шлёт stage_id ВМЕСТЕ с
  // position, а исполнителю-наблюдателю разрешены только галочка и колонка. Гейт —
  // на самой карточке (`KanbanCard draggable={canEdit}`): так снимаются и
  // обработчики, и a11y-атрибуты «draggable». Свою колонку наблюдатель меняет
  // селектом в карточке задачи.
  // 5px у мыши и 200мс у пальца держат ДВА жеста разом: клик по имени колонки
  // (переименование) и перетаскивание за тот же заголовок. Тронешь порог —
  // сломается либо правка имени, либо свайп ленты на телефоне.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 200, tolerance: 5 },
    }),
  )
  const isTouch = useIsTouch()

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
      if (t.done) s.done += 1
      m.set(t.parent_task_id, s)
    }
    return m
  }, [tasks.data])

  const columns: ColumnDef[] = useMemo(() => {
    const map = new Map<string, Task[]>()
    for (const t of tasks.data ?? []) {
      // Подзадачи живут в карточке родителя, а не отдельными карточками.
      if (t.parent_task_id) continue
      // Без статуса — не на доске (0046).
      if (!t.stage_id) continue
      const list = map.get(t.stage_id) ?? []
      list.push(t)
      map.set(t.stage_id, list)
    }
    const byPos = (a: Task, b: Task) => Number(a.position) - Number(b.position)
    return (stages.data ?? []).map((s) => ({
      dndId: `stage-${s.id}`,
      stage: s,
      name: s.name,
      tasks: (map.get(s.id) ?? []).sort(byPos),
      total: s.task_count ?? null,
    }))
  }, [tasks.data, stages.data])

  const activeTask = (tasks.data ?? []).find((t) => t.id === activeId) ?? null
  const activeColumn = columns.find((c) => c.dndId === activeId) ?? null

  const onDragStart = (e: DragStartEvent) => {
    setActiveId(String(e.active.id))
    setActiveType(e.active.data.current?.type === 'column' ? 'column' : 'task')
  }

  /**
   * Цели зависят от того, что тащим. Колонку сравниваем ТОЛЬКО с колонками:
   * `closestCorners` на смешанной ленте почти всегда отдаёт карточку (их больше
   * и они ближе к курсору) — тот же дефект, из-за которого `overColumnId`
   * считается здесь, а не в самой колонке.
   */
  const collisionDetection = useCallback<CollisionDetection>(
    (args) => {
      if (args.active.data.current?.type !== 'column') return closestCorners(args)
      return closestCenter({
        ...args,
        droppableContainers: args.droppableContainers.filter(
          (c) => c.data.current?.type === 'column',
        ),
      })
    },
    [],
  )

  const columnIdFor = (overId: string): string | null => {
    const byId = columns.find((c) => c.dndId === overId)
    if (byId) return byId.dndId
    return columns.find((c) => c.tasks.some((t) => t.id === overId))?.dndId ?? null
  }

  const onDragOver = (e: DragOverEvent) => {
    // У колонки приёмника нет: она встаёт между соседями, а не «внутрь».
    if (e.active.data.current?.type === 'column') {
      setOverColumnId(null)
      return
    }
    setOverColumnId(e.over ? columnIdFor(String(e.over.id)) : null)
  }

  const onColumnDragEnd = (e: DragEndEvent) => {
    if (!e.over) return
    const list = stages.data ?? []
    const byDndId = (dndId: string) => columns.find((c) => c.dndId === dndId)?.stage.id ?? ''
    const move = reorderStages(
      list,
      byDndId(String(e.active.id)),
      byDndId(String(e.over.id)),
    )
    if (!move) return
    updateStage.mutate({ stageId: move.stageId, position: move.position })
  }

  const onDragEnd = (e: DragEndEvent) => {
    const wasColumn = e.active.data.current?.type === 'column'
    setActiveId(null)
    setActiveType(null)
    setOverColumnId(null)
    if (wasColumn) {
      onColumnDragEnd(e)
      return
    }
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
    const samePosition = Math.abs(newPosition - Number(sourceTask.position)) < 1e-6
    const sameStage = sourceColumn.stage?.id === targetColumn.stage.id
    if (samePosition && sameStage) return

    update.mutate(
      sameStage
        ? { id: taskId, position: newPosition }
        : {
            // Перенос между колонками состояние задачи не трогает (0044),
            // поэтому оптимистичных зеркал больше нет.
            id: taskId,
            stage_id: targetColumn.stage.id,
            position: newPosition,
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
  // ВЫШЕ гардов: колонками управляют и из пустых состояний, иначе проект без
  // задач оказывается заперт — управление колонками живёт только здесь.
  // Это `const` и обычная функция, не хуки, так что порядок хуков не задет.
  // ОСТОРОЖНО: обернуть `moveStage` в useCallback значит увести хук ниже
  // ранних возвратов и сломать правило хуков.
  const stageList = stages.data ?? []
  const moveStage = (stage: TaskStage, dir: -1 | 1) => {
    const idx = stageList.findIndex((s) => s.id === stage.id)
    const next = idx + dir
    if (idx < 0 || next < 0 || next >= stageList.length) return
    updateStage.mutate({ stageId: stage.id, position: next })
  }
  const openNewStage = () => setNewStageOpen(true)
  // Диалоги колонок монтируются ОДИН раз и подмешиваются к любому состоянию:
  // иначе у каждой ветки завелась бы своя копия.
  const stageDialogs = (
    <>
      <StageFormDialog
        open={newStageOpen}
        onOpenChange={setNewStageOpen}
        projectId={projectId}
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
    </>
  )

  // `columns` бакетит только задачи С колонкой; `tasks.data` — весь список.
  // Разница между ними — это задачи, которых на доске нет: подсказка обязана
  // называть их число, иначе пустая лента читается как «задачи пропали».
  // Подзадачи не считаем — они живут в карточке родителя, а не столбцом.
  const stageless = (tasks.data ?? []).filter((t) => !t.parent_task_id && !t.stage_id).length
  const visible = columns.reduce((n, c) => n + c.tasks.length, 0)
  const hint = boardHint({ stages: stageList.length, stageless, visible })

  // Колонок нет вовсе — штатное состояние нового проекта (26.08): стартовую
  // четвёрку больше никто не навязывает. Показываем ровно то, чего не хватает,
  // — призрачную «+ Колонка» на месте первой колонки, ту же самую, что
  // замыкает ленту справа.
  if (stageList.length === 0) {
    return (
      <>
        {hint && (
          // Молчать здесь нельзя: у «Подбора» таких задач 1 277, и пустая
          // лента прочиталась бы как «задачи пропали».
          <p className="px-1 pb-3 text-[14px] leading-[1.45] text-text2">{hint}</p>
        )}
        {canEdit ? (
          <div className={LANE_CLASS}>
            <AddStageButton onClick={openNewStage} />
          </div>
        ) : (
          <TaskEmptyState
            title="Колонок пока нет"
            text="Их создаёт владелец или редактор проекта — до этого задачи живут в списке."
          />
        )}
        {stageDialogs}
      </>
    )
  }

  if (visible === 0 && activeFilterCount(filters ?? {}) > 0) {
    // Отдельной веткой и одним блоком: колонки с инпутами приглашали бы
    // создать задачу, которая тут же исчезнет — она не попадёт под фильтр.
    return (
      <TaskEmptyState
        title="Под фильтры не попала ни одна задача"
        text="Снимите часть условий — или посмотрите список целиком."
        cta="Сбросить фильтры"
        onCta={onResetFilters}
      />
    )
  }

  // Инпут быстрого создания — только в первой колонке: «Новая задача» из
  // сайдбара иначе молча падала в диалог.
  const firstStageIdx = 0
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={collisionDetection}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={() => {
        setActiveId(null)
        setActiveType(null)
        setOverColumnId(null)
      }}
    >
      {hint && (
        // ОДНА строка вместо плейсхолдера в каждой колонке: четыре одинаковых
        // сообщения читались бы как четыре разные проблемы (см. правило ниже).
        // Текст считает `lib/boardHints.ts` — там же он и покрыт тестами.
        <p className="px-1 pb-3 text-[14px] leading-[1.45] text-text2">{hint}</p>
      )}
      <div className={LANE_CLASS}>
        <SortableContext
          items={columns.map((c) => c.dndId)}
          strategy={horizontalListSortingStrategy}
        >
          {columns.map((col, i) => (
            <KanbanColumn
              key={col.dndId}
              boardEmpty={visible === 0}
              // Первая НАСТОЯЩАЯ колонка: у «Без колонки» (индекс 0, если есть)
              // инпута нет — «Новая задача» из сайдбара молча падала в диалог.
              quickCreateTarget={i === firstStageIdx}
              column={col}
              projectId={projectId}
              canEdit={canEdit}
              isOver={overColumnId === col.dndId}
              childrenByParent={childrenByParent}
              labelsByTask={labelsByTask}
              onTaskClick={onTaskClick}
              onToggleDone={toggleDone}
              onDeleteStage={(s) => setStageDelete(s)}
              extraMenu={
                // Порядок колонок меняют перетаскиванием за заголовок. На тач-
                // устройствах это неудобно: колонка шире экрана на 85%, а лента
                // листается свайпом — поэтому там пункты меню остаются.
                isTouch ? (
                  <>
                    <DropdownMenuItem onSelect={() => moveStage(col.stage, -1)}>
                      Левее
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => moveStage(col.stage, 1)}>
                      Правее
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                  </>
                ) : null
              }
            />
          ))}
        </SortableContext>
        {canEdit && <AddStageButton onClick={openNewStage} />}
      </div>
      <DragOverlay>
        {activeType === 'column' ? (
          activeColumn && (
            // Копия шапки, а не вся колонка с карточками: тащить визуально
            // тяжёлый столбец на телефоне — это лаг и мусор под пальцем.
            <div className="flex w-72 items-center gap-2 rounded-xl border border-amber/50 bg-bg-alt px-2.5 py-2 shadow-lg">
              <span className="min-w-0 truncate font-body text-[14px] font-semibold text-text">
                {activeColumn.name}
              </span>
              <span className="ml-auto font-mono text-[13px] text-text2">
                {activeColumn.tasks.length}
              </span>
            </div>
          )
        ) : (
          activeTask && <KanbanCard task={activeTask} overlay />
        )}
      </DragOverlay>
      {stageDialogs}
    </DndContext>
  )
}
