import { Loader2 } from 'lucide-react'

import { CustomFieldEditor } from '@/components/task/CustomFieldEditor'
import {
  useCustomFieldDefinitions,
  useSetTaskCustomValue,
  useTaskCustomValues,
} from '@/hooks/useCustomFields'
import { type CustomFieldValue } from '@/lib/customFields'

interface TaskCustomFieldsProps {
  taskId: string
  projectId: string
}

/** Renders every project field as an inline editor pre-populated from the
 *  task's stored value (if any). Owner-only field management (create/delete)
 *  lives in CustomFieldsManager (header). */
export function TaskCustomFields({ taskId, projectId }: TaskCustomFieldsProps) {
  const defs = useCustomFieldDefinitions(projectId)
  const values = useTaskCustomValues(taskId)
  const setValue = useSetTaskCustomValue(taskId)

  if (defs.isLoading || values.isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-text3">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Загружаем поля…
      </div>
    )
  }
  if (!defs.data || defs.data.length === 0) {
    return null
  }

  const byField = new Map<string, CustomFieldValue>()
  for (const v of values.data ?? []) byField.set(v.field_id, v)

  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-text3">
        Поля
      </h3>
      <div className="space-y-2">
        {defs.data.map((def) => {
          const current = byField.get(def.id)?.value ?? null
          return (
            <div
              key={def.id}
              className="grid grid-cols-[100px_1fr] items-center gap-3"
            >
              <label
                className="truncate text-xs font-medium text-text2"
                htmlFor={`cf-${def.id}`}
              >
                {def.name}
              </label>
              <div id={`cf-${def.id}`}>
                <CustomFieldEditor
                  definition={def}
                  value={current}
                  disabled={setValue.isPending}
                  onChange={(next) => {
                    setValue.mutate({ fieldId: def.id, value: next })
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
