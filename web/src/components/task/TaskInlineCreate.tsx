import { useState } from 'react'
import { toast } from 'sonner'

import { Input } from '@/components/ui/Input'
import { useCreateTask } from '@/hooks/useTasks'

interface TaskInlineCreateProps {
  projectId: string
  sectionId: string | null
}

/** Inline `+ Add task` row. Enter creates, Esc cancels (clears input). */
export function TaskInlineCreate({ projectId, sectionId }: TaskInlineCreateProps) {
  const [title, setTitle] = useState('')
  const create = useCreateTask(projectId)

  const submit = async () => {
    const trimmed = title.trim()
    if (!trimmed) return
    try {
      await create.mutateAsync({ title: trimmed, section_id: sectionId })
      setTitle('')
    } catch (err) {
      toast.error('Не удалось создать задачу', {
        description: (err as Error).message,
      })
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
      placeholder="+ Новая задача"
      disabled={create.isPending}
      className="border-transparent bg-transparent shadow-none focus-visible:border-amber"
    />
  )
}
