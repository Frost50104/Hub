import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { MoreHorizontal } from 'lucide-react'
import { useState, type CSSProperties, type ReactNode } from 'react'

import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { useUpdateStage } from '@/hooks/useStages'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { nextName } from '@/lib/renameDraft'
import { type TaskStage } from '@/lib/stages'
import { type SubtaskStats, type Task } from '@/lib/tasks'

import { KanbanCard } from './KanbanCard'

export interface ColumnDef {
  /** Колонка доски. Всегда есть: на доску попадают только задачи со статусом
   *  (0046), бакета «Без колонки» больше нет. */
  stage: TaskStage
  /** dnd-kit identifier — must be unique per column. */
  dndId: string
  name: string
  tasks: Task[]
  /** Тотал по колонке с сервера — правая часть «N из M». */
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
  /** Пуста ВСЯ доска: свой плейсхолдер колонка тогда не рисует —
   *  объяснение даёт одна строка над лентой. */
  boardEmpty?: boolean
  /** Меню колонки («…»): только удаление. Переименование живёт в заголовке. */
  onDeleteStage?: (stage: TaskStage) => void
  /** Дополнительные пункты меню — перестановка на тач-устройствах. */
  extraMenu?: ReactNode
}

/**
 * Колонка доски = ЭТАП задачи: 288px (`sm:w-72`), отбивка 4px, радиус 12.
 * Имя колонки — пользовательское, 14/600 обычным шрифтом, без точки и без
 * цветовой кодировки: цвет принадлежит приоритету и просрочке, а не колонке.
 * Счётчик — «N из M»: слева отрисовано (фильтры могли сузить), справа
 * тотал по колонке с сервера.
 *
 * Управление колонкой живёт в её заголовке, а не в меню (26.08):
 * - **порядок** — перетаскиванием за заголовок. Ручка именно он, а не отдельный
 *   грип: `PointerSensor` работает от 5px (`BoardView`), поэтому клик без
 *   движения драг не начинает и доживает до имени;
 * - **имя** — кликом по имени, инпут на месте заголовка (правила общие с
 *   папкой в сайдбаре: Enter и blur коммитят, Escape отменяет);
 * - в «…» осталось только «Удалить колонку» — плюс «Левее»/«Правее» на
 *   тач-устройствах, где перетаскивать колонку внутри свайп-ленты неудобно.
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
  boardEmpty = false,
  onDeleteStage,
  extraMenu,
}: KanbanColumnProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(column.name)
  const update = useUpdateStage(projectId)

  // Пока правят имя, колонка не тащится: выделение текста мышью — это движение
  // больше 5px, то есть ровно жест перетаскивания.
  const draggable = canEdit && !editing
  const sortable = useSortable({
    id: column.dndId,
    data: { type: 'column' },
    disabled: !draggable,
  })
  const style: CSSProperties = {
    transform: CSS.Transform.toString(sortable.transform),
    transition: sortable.transition,
    // Тащим над соседями, иначе колонка ныряет под следующую.
    zIndex: sortable.isDragging ? 20 : undefined,
  }

  const startRename = () => {
    if (!canEdit) return
    setDraft(column.name)
    setEditing(true)
  }

  const submitRename = () => {
    setEditing(false)
    const name = nextName(draft, column.name)
    if (name) update.mutate({ stageId: column.stage.id, name })
  }

  const receiving = sortable.isOver || isOverColumn
  const shown = column.tasks.length
  const counter =
    column.total != null && column.total !== shown ? `${shown} из ${column.total}` : String(shown)

  return (
    <div
      ref={sortable.setNodeRef}
      style={style}
      className={cn(
        'flex w-[85%] max-w-[320px] shrink-0 snap-start flex-col rounded-xl border border-dashed p-1 transition-colors sm:w-72 sm:max-w-none',
        receiving && !sortable.isDragging
          ? 'border-amber/50 bg-amber/[0.05]'
          : 'border-transparent bg-transparent',
        sortable.isDragging && 'opacity-60',
      )}
    >
      <header
        // Только `listeners`, без `attributes`: последние ставят на заголовок
        // `role="button"` и `tabIndex`, то есть обещают клавиатурное
        // перетаскивание, которого нет (KeyboardSensor на доске не подключён),
        // и заворачивают в кнопку две настоящие кнопки внутри — имя и «…».
        {...(draggable ? sortable.listeners : {})}
        aria-roledescription={draggable ? 'колонка, можно перетащить' : undefined}
        className={cn(
          'flex items-center gap-2 px-1.5 pb-2.5 pt-1.5',
          draggable && 'cursor-grab active:cursor-grabbing',
        )}
      >
        {editing ? (
          <input
            autoFocus
            // Выделяем при фокусе — то же правило, что у папки в сайдбаре:
            // переименование почти всегда замена имени целиком.
            onFocus={(e) => e.target.select()}
            value={draft}
            maxLength={255}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={submitRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submitRename()
              if (e.key === 'Escape') setEditing(false)
            }}
            aria-label={`Новое имя колонки «${column.name}»`}
            className="h-7 min-w-0 flex-1 rounded-md border border-glass-border bg-glass px-1.5 font-body text-[14px] font-semibold text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
          />
        ) : canEdit ? (
          // Заголовок остаётся заголовком: доска — это список колонок, и
          // структура h3 нужна не меньше, чем клик по имени.
          <h3 className="min-w-0">
            <button
              type="button"
              onClick={startRename}
              title="Переименовать колонку"
              className="w-full truncate rounded-md px-1 py-0.5 text-left font-body text-[14px] font-semibold text-text hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            >
              {column.name}
            </button>
          </h3>
        ) : (
          <h3 className="min-w-0 truncate font-body text-[14px] font-semibold text-text">
            {column.name}
          </h3>
        )}
        {!editing && (
          <span className="ml-auto shrink-0 font-mono text-[13px] text-text2">{counter}</span>
        )}
        {canEdit && !editing && (onDeleteStage || extraMenu) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={`Действия с колонкой «${column.name}»`}
                // Radix открывает меню по pointerdown, а на этом же заголовке
                // висят listeners перетаскивания: без гашения нажатие делало бы
                // и то, и другое.
                onPointerDown={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
                className="-my-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {extraMenu}
              {onDeleteStage && (
                <DropdownMenuItem destructive onSelect={() => onDeleteStage(column.stage)}>
                  Удалить колонку
                </DropdownMenuItem>
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
              draggable={canEdit}
              onClick={() => onTaskClick(t.id)}
              onToggleDone={
                t.can_complete === false ? undefined : () => onToggleDone(t)
              }
            />
          ))}
        </SortableContext>

        {column.tasks.length === 0 && !boardEmpty && (
          // Заголовка нет: продукт говорит «Здесь пока пусто», а не командует.
          // На ПОЛНОСТЬЮ пустой доске этот блок гасится: четыре одинаковых
          // сообщения читались бы как четыре проблемы, да и «перетащите
          // задачу» было бы враньём — перетаскивать нечего.
          <div className="flex flex-col gap-2 rounded-xl border border-dashed border-glass-border px-3.5 py-[18px] text-center">
            <p className="text-[14px] leading-[1.45] text-text2">Здесь пока пусто.</p>
            <p className="text-[13px] leading-[1.45] text-text2">
              Перетащите задачу или создайте новую внизу колонки.
            </p>
          </div>
        )}

        {canEdit && (
          <TaskInlineCreate
            projectId={projectId}
            stageId={column.stage.id}
            quickCreateTarget={quickCreateTarget}
          />
        )}
      </div>
    </div>
  )
}
