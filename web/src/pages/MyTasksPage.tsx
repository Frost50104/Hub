import { useState } from 'react'

import { TaskRow } from '@/components/task/TaskRow'
import { useMyTasks, type DueWindow } from '@/hooks/useMyTasks'
import { useUpdateTask } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'

const TABS: { key: DueWindow; label: string }[] = [
  { key: 'upcoming', label: 'Предстоит' },
  { key: 'overdue', label: 'Просрочено' },
  { key: 'today', label: 'Сегодня' },
  { key: 'all', label: 'Все' },
]

export function MyTasksPage() {
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
