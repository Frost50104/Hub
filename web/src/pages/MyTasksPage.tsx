import { Filter } from 'lucide-react'
import { useState } from 'react'

import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { TaskRow } from '@/components/task/TaskRow'
import {
  BottomSheet,
  BottomSheetItem,
} from '@/components/ui/BottomSheet'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMyTasks, type DueWindow } from '@/hooks/useMyTasks'
import { useProjects } from '@/hooks/useProjects'
import { useUpdateTask } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'

const TABS: { key: DueWindow; label: string }[] = [
  { key: 'upcoming', label: 'Предстоит' },
  { key: 'overdue', label: 'Просрочено' },
  { key: 'today', label: 'Сегодня' },
  { key: 'all', label: 'Все' },
]

export function MyTasksPage() {
  const isDesktop = useIsDesktop()
  return isDesktop ? <DesktopMyTasks /> : <MobileMyTasks />
}

function MobileMyTasks() {
  const [tab, setTab] = useState<DueWindow>('upcoming')
  const [pickerOpen, setPickerOpen] = useState(false)
  const tasks = useMyTasks({ due_window: tab })
  const projects = useProjects()
  const update = useUpdateTask('')
  const projectsById = new Map((projects.data ?? []).map((p) => [p.id, p]))

  const current = TABS.find((t) => t.key === tab)!

  return (
    <>
      <MobilePageHeader title="Мои задачи" withOverflowMenu />

      <div className="border-y border-glass-border bg-bg-alt/80 px-4 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-full border border-glass-border bg-glass px-3 py-1 text-sm text-text active:bg-surface"
          >
            <Filter className="h-3.5 w-3.5" /> {current.label}
          </button>
        </div>
      </div>

      <div>
        {tasks.isLoading && (
          <p className="px-4 py-4 text-sm text-text2">Загружаем…</p>
        )}
        {tasks.data && tasks.data.length === 0 && (
          <p className="px-4 py-10 text-center text-sm text-text3">
            {tab === 'overdue' ? 'Нет просроченных — отлично!' : 'Здесь пока пусто.'}
          </p>
        )}
        {tasks.data?.map((t) => (
          <MobileTaskRow
            key={t.id}
            task={t}
            subtitle={
              t.project_id ? projectsById.get(t.project_id)?.name : undefined
            }
            onToggleDone={() =>
              update.mutate({
                id: t.id,
                status: t.status === 'done' ? 'todo' : 'done',
              })
            }
          />
        ))}
      </div>

      <BottomSheet
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        title="Окно дедлайнов"
      >
        {TABS.map((t) => (
          <BottomSheetItem
            key={t.key}
            onClick={() => {
              setTab(t.key)
              setPickerOpen(false)
            }}
            trailing={tab === t.key ? '✓' : null}
          >
            {t.label}
          </BottomSheetItem>
        ))}
      </BottomSheet>

      <FloatingActionButton />
    </>
  )
}

function DesktopMyTasks() {
  const [tab, setTab] = useState<DueWindow>('upcoming')
  const tasks = useMyTasks({ due_window: tab })
  const update = useUpdateTask('')

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <header>
        <h1 className="font-display text-2xl font-semibold">Мои задачи</h1>
        <p className="text-sm text-text2">
          Всё, что назначено на вас, в одном месте.
        </p>
      </header>

      <div className="flex gap-1 border-b border-glass-border">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              '-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors',
              tab === key
                ? 'border-amber text-text'
                : 'border-transparent text-text2 hover:text-text',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div>
        {tasks.isLoading && <p className="text-sm text-text2">Загружаем…</p>}
        {tasks.error && (
          <p className="text-sm text-red">
            Ошибка: {(tasks.error as Error).message}
          </p>
        )}
        {tasks.data && tasks.data.length === 0 && (
          <p className="rounded-lg border border-glass-border p-6 text-center text-sm text-text3">
            {tab === 'overdue'
              ? 'Нет просроченных задач — отлично!'
              : 'Здесь пока пусто.'}
          </p>
        )}
        {tasks.data?.map((t) => (
          <TaskRow
            key={t.id}
            task={t}
            onToggleDone={() =>
              update.mutate({
                id: t.id,
                status: t.status === 'done' ? 'todo' : 'done',
              })
            }
          />
        ))}
      </div>
    </div>
  )
}
