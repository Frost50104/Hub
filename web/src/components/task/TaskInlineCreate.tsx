import { useState } from 'react'

import { Input } from '@/components/ui/Input'
import { useCreateTask } from '@/hooks/useTasks'

interface TaskInlineCreateProps {
  projectId: string
  sectionId: string | null
  /** Создаёт подзадачу указанной задачи (секция при этом не назначается). */
  parentTaskId?: string
  placeholder?: string
}

/** Inline `+ Add task` row. Enter creates, Esc cancels (clears input). */
export function TaskInlineCreate({
  projectId,
  sectionId,
  parentTaskId,
  placeholder = '+ Новая задача',
}: TaskInlineCreateProps) {
  const [title, setTitle] = useState('')
  const create = useCreateTask(projectId)

  const submit = async () => {
    const trimmed = title.trim()
    if (!trimmed) return
    try {
      await create.mutateAsync({
        title: trimmed,
        section_id: sectionId,
        parent_task_id: parentTaskId,
      })
      setTitle('')
    } catch {
      // ввод сохраняем в поле; тост показывает глобальный onError мутаций
    }
  }

  return (
    <Input
      value={title}
      onChange={(e) => setTitle(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          void submit()
        } else if (e.key === 'Escape') {
          setTitle('')
        }
      }}
      placeholder={placeholder}
      disabled={create.isPending}
      className="border-transparent bg-transparent shadow-none focus-visible:border-amber"
    />
  )
}
