import { useEffect, useMemo, useRef, useState } from 'react'

import { Input } from '@/components/ui/Input'
import { useCreateTask } from '@/hooks/useTasks'
import { createInlineDraft } from '@/lib/inlineDraft'
import { useInlineCreateTarget } from '@/lib/quickCreate'

interface TaskInlineCreateProps {
  projectId: string
  sectionId: string | null
  /** Колонка доски: задача рождается сразу в ней. */
  stageId?: string | null
  parentTaskId?: string | null
  placeholder?: string
  /** Этот инпут принимает фокус от «Новая задача» в сайдбаре/шапке. */
  quickCreateTarget?: boolean
}

/**
 * Инлайн-строка «+ Новая задача» / «+ Подзадача».
 *
 * Правила — в `lib/inlineDraft.ts` (там же тесты): Enter создаёт и оставляет
 * фокус для следующей (Enter-Enter-Enter — задачи создаются по очереди, в
 * порядке ввода); потеря фокуса и размонтирование создают непустой черновик
 * (как Asana — ввёл и ушёл, задача есть); Escape — отмена. Раньше черновик жил
 * только до Enter и терялся при любом клике мимо (ОС тестировщика 2026-08).
 *
 * Инпут не блокируется на время запроса: `disabled` снимал бы фокус и давал
 * синтетический blur — второй коммит того же текста.
 */
export function TaskInlineCreate({
  projectId,
  sectionId,
  stageId,
  parentTaskId,
  placeholder = '+ Новая задача',
  quickCreateTarget = false,
}: TaskInlineCreateProps) {
  const [title, setTitle] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const create = useCreateTask(projectId)
  useInlineCreateTarget(inputRef, projectId, quickCreateTarget)

  // SubtaskList меняет parentTaskId без remount (переключение задачи в
  // панели) — читаем актуальные пропсы из ref в момент коммита.
  const propsRef = useRef({ sectionId, stageId, parentTaskId })
  propsRef.current = { sectionId, stageId, parentTaskId }
  const createRef = useRef(create)
  createRef.current = create

  const draft = useMemo(
    () =>
      createInlineDraft({
        onChange: setTitle,
        submit: (text) =>
          createRef.current.mutateAsync({
            title: text,
            section_id: propsRef.current.sectionId,
            stage_id: propsRef.current.stageId ?? undefined,
            parent_task_id: propsRef.current.parentTaskId ?? undefined,
          }),
      }),
    [],
  )

  // Размонтирование (ушли со страницы, закрыли карточку) коммитит черновик.
  useEffect(() => () => draft.unmount(), [draft])

  return (
    <Input
      ref={inputRef}
      value={title}
      onChange={(e) => draft.change(e.target.value)}
      onBlur={() => draft.blur()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          draft.enter()
        } else if (e.key === 'Escape') {
          draft.escape()
          e.currentTarget.blur()
        }
      }}
      enterKeyHint="done"
      placeholder={placeholder}
      aria-busy={create.isPending || undefined}
      className="border-transparent bg-transparent shadow-none focus-visible:border-amber"
    />
  )
}
