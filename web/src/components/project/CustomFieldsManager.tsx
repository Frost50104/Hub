import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, Pencil, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState, type CSSProperties } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import {
  useCreateCustomField,
  useCustomFieldDefinitions,
  useDeleteCustomField,
  useUpdateCustomField,
} from '@/hooks/useCustomFields'
import { cn } from '@/lib/cn'
import {
  CUSTOM_FIELD_TYPE_LABEL,
  type CustomFieldDefinition,
  type CustomFieldOption,
  type CustomFieldType,
} from '@/lib/customFields'

interface CustomFieldsManagerProps {
  projectId: string
  open: boolean
  onOpenChange: (v: boolean) => void
}

const NON_OPTION_TYPES: CustomFieldType[] = [
  'text',
  'number',
  'date',
  'person',
  'checkbox',
]
const OPTION_TYPES: CustomFieldType[] = ['select', 'multi_select']
const ALL_TYPES: CustomFieldType[] = [...NON_OPTION_TYPES, ...OPTION_TYPES]

let optionTmpCounter = 0

export function CustomFieldsManager({
  projectId,
  open,
  onOpenChange,
}: CustomFieldsManagerProps) {
  const defs = useCustomFieldDefinitions(projectId)
  const create = useCreateCustomField(projectId)
  const update = useUpdateCustomField(projectId)
  const remove = useDeleteCustomField(projectId)

  const [name, setName] = useState('')
  const [type, setType] = useState<CustomFieldType>('text')
  const [options, setOptions] = useState<CustomFieldOption[]>([])

  // Local order copy so we can do optimistic drag reorder before the server
  // confirms the new positions.
  const [localOrder, setLocalOrder] = useState<CustomFieldDefinition[]>([])
  useEffect(() => {
    if (defs.data) setLocalOrder(defs.data)
  }, [defs.data])

  const isOptionType = OPTION_TYPES.includes(type)
  const valid =
    name.trim().length > 0 &&
    (!isOptionType ||
      (options.length > 0 && options.every((o) => o.label.trim().length > 0)))

  const reset = () => {
    setName('')
    setType('text')
    setOptions([])
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!valid) return
    try {
      await create.mutateAsync({
        name: name.trim(),
        type,
        options: isOptionType
          ? options.map((o) => ({
              id: o.id,
              label: o.label.trim(),
              color: o.color,
            }))
          : undefined,
      })
      toast.success(`Поле «${name.trim()}» создано`)
      reset()
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  const addOption = () => {
    optionTmpCounter += 1
    setOptions((prev) => [
      ...prev,
      { id: `opt_${Date.now()}_${optionTmpCounter}`, label: '' },
    ])
  }

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return
    const oldIdx = localOrder.findIndex((d) => d.id === e.active.id)
    const newIdx = localOrder.findIndex((d) => d.id === e.over!.id)
    if (oldIdx === -1 || newIdx === -1) return

    const reordered = arrayMove(localOrder, oldIdx, newIdx)
    setLocalOrder(reordered)

    // Compute new position for the moved item: midpoint between neighbours,
    // or +1 / -1 at the edges. Same pattern as kanban DnD.
    const moved = reordered[newIdx]!
    const before = newIdx > 0 ? Number(reordered[newIdx - 1]!.position) : null
    const after =
      newIdx < reordered.length - 1
        ? Number(reordered[newIdx + 1]!.position)
        : null
    let newPosition: number
    if (before === null && after !== null) newPosition = after - 1
    else if (after === null && before !== null) newPosition = before + 1
    else if (before !== null && after !== null) newPosition = (before + after) / 2
    else newPosition = Number(moved.position)

    update.mutate({ fieldId: moved.id, body: { position: newPosition } })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) reset()
        onOpenChange(v)
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Поля проекта</DialogTitle>
          <DialogDescription>
            Дополнительные поля для задач: текст, число, дата, выбор, человек,
            чекбокс. Видны на всех задачах проекта. Drag-handle меняет порядок.
          </DialogDescription>
        </DialogHeader>

        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text3">
            Существующие
          </h3>
          {defs.isLoading && <p className="text-sm text-text2">Загружаем…</p>}
          {defs.data?.length === 0 && (
            <p className="text-sm text-text3">Пока нет полей.</p>
          )}

          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={onDragEnd}
          >
            <SortableContext
              items={localOrder.map((d) => d.id)}
              strategy={verticalListSortingStrategy}
            >
              <ul className="space-y-1">
                {localOrder.map((d) => (
                  <SortableFieldRow
                    key={d.id}
                    definition={d}
                    onRename={async (newName) => {
                      try {
                        await update.mutateAsync({
                          fieldId: d.id,
                          body: { name: newName.trim() },
                        })
                        toast.success(`Переименовано в «${newName.trim()}»`)
                      } catch {
                        // тост показывает глобальный onError мутаций
                      }
                    }}
                    onDelete={async () => {
                      if (!confirm(`Удалить поле «${d.name}»?`)) return
                      try {
                        await remove.mutateAsync(d.id)
                        toast.success(`Поле «${d.name}» удалено`)
                      } catch {
                        // тост показывает глобальный onError мутаций
                      }
                    }}
                  />
                ))}
              </ul>
            </SortableContext>
          </DndContext>
        </section>

        <form onSubmit={submit} className="space-y-3 border-t border-glass-border pt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text3">
            Новое поле
          </h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_180px]">
            <div className="space-y-1.5">
              <Label htmlFor="cf-name">Название</Label>
              <Input
                id="cf-name"
                placeholder="Бюджет"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={create.isPending}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cf-type">Тип</Label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="secondary"
                    className="w-full justify-between"
                    id="cf-type"
                  >
                    {CUSTOM_FIELD_TYPE_LABEL[type]}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-[180px]">
                  {ALL_TYPES.map((t) => (
                    <DropdownMenuItem
                      key={t}
                      onSelect={() => {
                        setType(t)
                        if (!OPTION_TYPES.includes(t)) setOptions([])
                      }}
                    >
                      {CUSTOM_FIELD_TYPE_LABEL[t]}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>

          {isOptionType && (
            <div className="space-y-2">
              <Label>Опции</Label>
              <div className="space-y-1.5">
                {options.map((opt, i) => (
                  <div key={opt.id} className="flex items-center gap-2">
                    <Input
                      placeholder="Название опции"
                      value={opt.label}
                      onChange={(e) =>
                        setOptions((prev) =>
                          prev.map((o, j) =>
                            j === i ? { ...o, label: e.target.value } : o,
                          ),
                        )
                      }
                      disabled={create.isPending}
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setOptions((prev) => prev.filter((_, j) => j !== i))
                      }
                      className="rounded p-1.5 text-text3 hover:bg-glass hover:text-red focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                      aria-label="Удалить опцию"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={addOption}
                  className={cn(
                    'flex items-center gap-1 rounded px-1 text-sm text-text2 hover:text-amber focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
                  )}
                >
                  <Plus className="h-3.5 w-3.5" /> Добавить опцию
                </button>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={create.isPending}
            >
              Закрыть
            </Button>
            <Button type="submit" disabled={!valid || create.isPending}>
              {create.isPending ? 'Создаём…' : 'Создать поле'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ─── Sortable row ───────────────────────────────────────────────────────────

interface SortableFieldRowProps {
  definition: CustomFieldDefinition
  onRename: (newName: string) => Promise<void>
  onDelete: () => Promise<void>
}

function SortableFieldRow({ definition, onRename, onDelete }: SortableFieldRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: definition.id })
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(definition.name)

  // If the upstream `definition.name` changes (server confirmed rename),
  // sync local draft so the input isn't stale on next edit.
  useEffect(() => {
    if (!editing) setDraft(definition.name)
  }, [definition.name, editing])

  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  const commit = async () => {
    const trimmed = draft.trim()
    if (!trimmed) {
      setDraft(definition.name)
      setEditing(false)
      return
    }
    if (trimmed === definition.name) {
      setEditing(false)
      return
    }
    await onRename(trimmed)
    setEditing(false)
  }

  return (
    <li
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-2 rounded-md border border-glass-border bg-surface px-2 py-2 text-sm"
    >
      <button
        type="button"
        {...attributes}
        {...listeners}
        className="cursor-grab text-text3 hover:text-text2 active:cursor-grabbing focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
        aria-label="Перетащить"
        title="Перетащить, чтобы изменить порядок"
      >
        <GripVertical className="h-4 w-4" />
      </button>

      <div className="flex min-w-0 flex-1 items-center gap-2">
        {editing ? (
          <Input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                ;(e.target as HTMLInputElement).blur()
              } else if (e.key === 'Escape') {
                setDraft(definition.name)
                setEditing(false)
              }
            }}
            className="h-7"
          />
        ) : (
          <>
            <button
              type="button"
              onClick={() => setEditing(true)}
              onDoubleClick={() => setEditing(true)}
              className="flex flex-1 items-center gap-1 truncate text-left text-text hover:text-amber focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              title="Переименовать"
            >
              <span className="truncate">{definition.name}</span>
              <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-100" />
            </button>
            <span className="shrink-0 rounded bg-glass px-1.5 py-0.5 text-[10px] text-text3">
              {CUSTOM_FIELD_TYPE_LABEL[definition.type]}
            </span>
            {(definition.type === 'select' ||
              definition.type === 'multi_select') && (
              <span className="shrink-0 text-[10px] text-text3">
                {definition.options.length} опц.
              </span>
            )}
          </>
        )}
      </div>

      <button
        type="button"
        onClick={onDelete}
        className="rounded p-1 text-text3 hover:bg-glass hover:text-red focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
        aria-label={`Удалить ${definition.name}`}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </li>
  )
}
