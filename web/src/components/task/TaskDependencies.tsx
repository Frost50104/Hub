import { ChevronDown, Link as LinkIcon, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import {
  useAddDependency,
  useRemoveDependency,
  useTaskDependencies,
} from '@/hooks/useTaskDependencies'
import { useTasks } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { type DependencyPeer } from '@/lib/timeline'

interface TaskDependenciesProps {
  taskId: string
  projectId: string
}

const STATUS_TONE: Record<DependencyPeer['status'], string> = {
  todo: 'text-text3',
  in_progress: 'text-amber',
  in_review: 'text-amber',
  done: 'text-green',
}

/**
 * "Зависит от" + "Блокирует" секция в TaskDetailDrawer. Создание — dropdown
 * со списком задач проекта, без выбранных уже peers и без самой себя.
 * Сервер отвергает циклы (409); тост покажет это пользователю.
 */
export function TaskDependencies({ taskId, projectId }: TaskDependenciesProps) {
  const deps = useTaskDependencies(taskId)
  const allTasks = useTasks(projectId)
  const add = useAddDependency(taskId, projectId)
  const remove = useRemoveDependency(taskId, projectId)
  const [pickerOpen, setPickerOpen] = useState(false)

  const existingIds = new Set<string>([
    taskId,
    ...(deps.data?.predecessors ?? []).map((p) => p.id),
    ...(deps.data?.successors ?? []).map((s) => s.id),
  ])
  const candidates = (allTasks.data ?? []).filter(
    (t) => !existingIds.has(t.id),
  )

  const onAdd = async (predId: string) => {
    setPickerOpen(false)
    try {
      await add.mutateAsync(predId)
      toast.success('Зависимость добавлена')
    } catch {
      // тост (включая 409 о цикле) показывает глобальный onError мутаций
    }
  }

  const onRemove = async (predId: string) => {
    try {
      await remove.mutateAsync(predId)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  if (deps.isLoading) return null

  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-text3">
        Зависимости
      </h3>

      {deps.isError && (
        <p className="text-xs text-red">Не удалось загрузить зависимости.</p>
      )}

      <div className="space-y-1">
        <p className="text-[10px] uppercase tracking-wider text-text3">
          Зависит от
        </p>
        {deps.data?.predecessors.length === 0 && (
          <p className="text-xs text-text3">—</p>
        )}
        <ul className="space-y-1">
          {deps.data?.predecessors.map((p) => (
            <li
              key={p.id}
              className="flex items-center justify-between gap-2 rounded-md border border-glass-border bg-surface px-2 py-1 text-xs"
            >
              <span className="flex min-w-0 items-center gap-2">
                <LinkIcon className={cn('h-3 w-3', STATUS_TONE[p.status])} />
                <span className="truncate text-text">{p.title}</span>
              </span>
              <button
                type="button"
                onClick={() => onRemove(p.id)}
                className="rounded p-1 text-text3 hover:bg-glass hover:text-red focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                aria-label="Удалить связь"
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>

        <DropdownMenu open={pickerOpen} onOpenChange={setPickerOpen}>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="mt-1 flex items-center gap-1 rounded px-1 text-[11px] text-text2 hover:text-amber focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            >
              <ChevronDown className="h-3 w-3" />
              Добавить
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="max-h-[280px] w-[280px] overflow-y-auto">
            {candidates.length === 0 && (
              <p className="px-2 py-1.5 text-xs text-text3">Нет доступных задач</p>
            )}
            {candidates.map((c) => (
              <DropdownMenuItem key={c.id} onSelect={() => onAdd(c.id)}>
                <span className="truncate">{c.title}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {deps.data && deps.data.successors.length > 0 && (
        <div className="space-y-1 pt-1">
          <p className="text-[10px] uppercase tracking-wider text-text3">
            Блокирует
          </p>
          <ul className="space-y-1">
            {deps.data.successors.map((s) => (
              <li
                key={s.id}
                className="flex items-center gap-2 rounded-md border border-glass-border bg-surface px-2 py-1 text-xs"
              >
                <LinkIcon className={cn('h-3 w-3', STATUS_TONE[s.status])} />
                <span className="truncate text-text">{s.title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
