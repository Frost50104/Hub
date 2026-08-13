import {
  CheckCircle2,
  ChevronDown,
  Circle,
  ClipboardCheck,
  Clock,
  Link as LinkIcon,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useLabelAssignments, useLabels } from '@/hooks/useLabels'
import { useProject, useProjectSections } from '@/hooks/useProjects'
import {
  useAddDependency,
  useRemoveDependency,
  useTaskDependencies,
} from '@/hooks/useTaskDependencies'
import { useTasks } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { taskKey, type TaskStatus } from '@/lib/tasks'
import { type DependencyPeer } from '@/lib/timeline'

interface TaskDependenciesProps {
  taskId: string
  projectId: string
  /** false → viewer: без «Добавить» и крестиков (сервер и так вернёт 403). */
  canEdit?: boolean
}

const STATUS_TONE: Record<DependencyPeer['status'], string> = {
  todo: 'text-text3',
  in_progress: 'text-amber',
  in_review: 'text-amber',
  done: 'text-green',
}

const STATUS_ICON: Record<TaskStatus, typeof Circle> = {
  todo: Circle,
  in_progress: Clock,
  in_review: ClipboardCheck,
  done: CheckCircle2,
}

/** Пикер показывает максимум столько совпадений (виртуализации нет). */
const MAX_VISIBLE = 50

/**
 * "Зависит от" + "Блокирует" секция в TaskDetailDrawer. Пикер — по паттерну
 * PeoplePicker (поиск внутри дропдауна): ОС 13.08 — «все задачи без меток,
 * названия обрезаются, похожие неразличимы». Пункт несёт номер KEY-42,
 * статус, полное название (2 строки), секцию и метки.
 * Сервер отвергает циклы (409); тост покажет это пользователю.
 */
export function TaskDependencies({
  taskId,
  projectId,
  canEdit = true,
}: TaskDependenciesProps) {
  const deps = useTaskDependencies(taskId)
  const allTasks = useTasks(projectId)
  const add = useAddDependency(taskId, projectId)
  const remove = useRemoveDependency(taskId, projectId)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [rawQuery, setRawQuery] = useState('')
  const query = useDebouncedValue(rawQuery.trim().toLowerCase(), 150)

  // Всё уже в кэше страницы проекта — дополнительного трафика нет.
  const projectKey = useProject(projectId).data?.key ?? null
  const sections = useProjectSections(projectId)
  const labels = useLabels(projectId)
  const assignments = useLabelAssignments(projectId)

  const sectionName = new Map((sections.data ?? []).map((s) => [s.id, s.name]))
  const labelById = new Map((labels.data ?? []).map((l) => [l.id, l]))
  const labelsByTask = new Map<string, Label[]>()
  for (const a of assignments.data ?? []) {
    const l = labelById.get(a.label_id)
    if (!l) continue
    const list = labelsByTask.get(a.task_id)
    if (list) list.push(l)
    else labelsByTask.set(a.task_id, [l])
  }

  const existingIds = new Set<string>([
    taskId,
    ...(deps.data?.predecessors ?? []).map((p) => p.id),
    ...(deps.data?.successors ?? []).map((s) => s.id),
  ])
  // Свои подзадачи из кандидатов исключаем — «задача зависит от собственной
  // подзадачи» дублирует смысл подзадач и шумит в пикере.
  const candidates = (allTasks.data ?? []).filter((t) => {
    if (existingIds.has(t.id) || t.parent_task_id === taskId) return false
    if (!query) return true
    const key = taskKey(projectKey, t.seq)?.toLowerCase()
    return (
      t.title.toLowerCase().includes(query) ||
      (key !== undefined && key !== null && key.includes(query))
    )
  })
  const visible = candidates.slice(0, MAX_VISIBLE)

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

  const peerChip = (p: DependencyPeer) => (
    <span className="flex min-w-0 items-center gap-2">
      <LinkIcon className={cn('h-3 w-3 shrink-0', STATUS_TONE[p.status])} />
      {projectKey && (
        <span className="shrink-0 font-mono text-[10px] text-text3">
          {projectKey}-{p.seq}
        </span>
      )}
      <span className="truncate text-text" title={p.title}>
        {p.title}
      </span>
    </span>
  )

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
              {peerChip(p)}
              {canEdit && (
                <button
                  type="button"
                  onClick={() => onRemove(p.id)}
                  className="rounded p-1 text-text3 hover:bg-glass hover:text-red focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                  aria-label="Удалить связь"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </li>
          ))}
        </ul>

        {canEdit && (
          <DropdownMenu
            open={pickerOpen}
            onOpenChange={(open) => {
              setPickerOpen(open)
              if (!open) setRawQuery('')
            }}
          >
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="mt-1 flex items-center gap-1 rounded px-1 text-[11px] text-text2 hover:text-amber focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              >
                <ChevronDown className="h-3 w-3" />
                Добавить
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              className="max-h-[320px] w-[360px] overflow-y-auto"
            >
              <div className="px-2 py-1">
                <input
                  type="text"
                  placeholder="Поиск по названию или номеру…"
                  value={rawQuery}
                  onChange={(e) => setRawQuery(e.target.value)}
                  className="w-full rounded border border-glass-border bg-glass px-2 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                />
              </div>
              {visible.length === 0 && (
                <p className="px-2 py-1.5 text-xs text-text3">
                  {query ? 'Ничего не нашли' : 'Нет доступных задач'}
                </p>
              )}
              {visible.map((c) => {
                const StatusIcon = STATUS_ICON[c.status]
                const cLabels = labelsByTask.get(c.id) ?? []
                const section = c.section_id
                  ? sectionName.get(c.section_id)
                  : undefined
                return (
                  <DropdownMenuItem key={c.id} onSelect={() => onAdd(c.id)}>
                    <div className="flex min-w-0 flex-1 items-start gap-2">
                      <StatusIcon
                        className={cn(
                          'mt-0.5 h-3.5 w-3.5 shrink-0',
                          STATUS_TONE[c.status],
                        )}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm leading-snug" title={c.title}>
                          {projectKey && c.seq != null && (
                            <span className="mr-1.5 font-mono text-[10px] text-text3">
                              {projectKey}-{c.seq}
                            </span>
                          )}
                          <span className="line-clamp-2 inline">{c.title}</span>
                        </p>
                        {(section || cLabels.length > 0) && (
                          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-text3">
                            {section && <span className="truncate">{section}</span>}
                            {cLabels.slice(0, 3).map((l) => (
                              <span
                                key={l.id}
                                className="inline-flex items-center gap-1 rounded-full border border-glass-border px-1.5 text-text2"
                              >
                                <span
                                  className="h-1.5 w-1.5 rounded-full"
                                  style={{ backgroundColor: l.color }}
                                  aria-hidden
                                />
                                {l.name}
                              </span>
                            ))}
                            {cLabels.length > 3 && <span>+{cLabels.length - 3}</span>}
                          </p>
                        )}
                      </div>
                    </div>
                  </DropdownMenuItem>
                )
              })}
              {candidates.length > MAX_VISIBLE && (
                <p className="px-2 py-1.5 text-[10px] text-text3">
                  Показаны первые {MAX_VISIBLE} из {candidates.length} — уточните
                  запрос.
                </p>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
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
                {peerChip(s)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
