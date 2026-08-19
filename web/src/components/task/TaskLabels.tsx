import { Check, Plus, X } from 'lucide-react'
import { useMemo } from 'react'

import { DrawerSection } from '@/components/task/DrawerSection'
import { TaskLabelChip } from '@/components/task/TaskLabelChip'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import {
  useAssignLabel,
  useLabelAssignments,
  useLabels,
  useUnassignLabel,
} from '@/hooks/useLabels'

interface TaskLabelsProps {
  taskId: string
  projectId: string
  canEdit: boolean
  /** Без заголовка секции: карточка задачи кладёт метки строкой в <dl>. */
  bare?: boolean
}

/**
 * Секция «Метки» в карточке задачи: чипы (цветная точка + имя — тема-безопасно
 * для произвольного hex) + мультиселект-меню.
 */
export function TaskLabels({ taskId, projectId, canEdit, bare }: TaskLabelsProps) {
  const labels = useLabels(projectId)
  const assignments = useLabelAssignments(projectId)
  const assign = useAssignLabel(projectId)
  const unassign = useUnassignLabel(projectId)

  const mine = useMemo(
    () =>
      new Set(
        (assignments.data ?? [])
          .filter((a) => a.task_id === taskId)
          .map((a) => a.label_id),
      ),
    [assignments.data, taskId],
  )
  const active = (labels.data ?? []).filter((l) => mine.has(l.id))

  // Без меток в проекте и без прав секция не нужна.
  if ((labels.data?.length ?? 0) === 0 && active.length === 0) return null

  const row = (
    <div className="flex flex-wrap items-center gap-1.5">
      {active.map((l) => (
        <span key={l.id} className="relative inline-flex items-center">
          <TaskLabelChip label={l} size="md" className={canEdit ? 'pr-1' : undefined} />
          {canEdit && (
            <button
              type="button"
              onClick={() => unassign.mutate({ taskId, labelId: l.id })}
              aria-label={`Снять метку ${l.name}`}
              className="-ml-1 flex h-[26px] w-5 items-center justify-center rounded-r-md text-text2 hover:text-red"
            >
              <X className="h-3 w-3" strokeWidth={2.4} />
            </button>
          )}
        </span>
      ))}

      {canEdit && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="inline-flex h-[26px] items-center gap-1 rounded-full border border-dashed border-glass-border px-2.5 text-[13px] font-semibold text-text2 hover:border-amber hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            >
              <Plus className="h-3 w-3" strokeWidth={2.2} /> Метка
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-[220px]">
            {(labels.data ?? []).map((l) => {
              const isOn = mine.has(l.id)
              return (
                <DropdownMenuItem
                  key={l.id}
                  onSelect={(e) => {
                    e.preventDefault() // мультиселект: меню не закрываем
                    if (isOn) unassign.mutate({ taskId, labelId: l.id })
                    else assign.mutate({ taskId, labelId: l.id })
                  }}
                >
                  <span
                    className="mr-2 h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: l.color }}
                    aria-hidden
                  />
                  <span className="flex-1 truncate">{l.name}</span>
                  {isOn && <Check className="h-3.5 w-3.5" />}
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )

  if (bare) return row

  return (
    <DrawerSection title="Метки">{row}</DrawerSection>
  )
}
