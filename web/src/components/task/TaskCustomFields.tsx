import { Loader2 } from 'lucide-react'
import { Fragment } from 'react'

import { DrawerSection } from '@/components/task/DrawerSection'

import { CustomFieldEditor } from '@/components/task/CustomFieldEditor'
import { PropertyRow } from '@/components/ui/PropertyRows'
import {
  useCustomFieldDefinitions,
  useSetTaskCustomValue,
  useTaskCustomValues,
} from '@/hooks/useCustomFields'
import { type CustomFieldValue } from '@/lib/customFields'

interface TaskCustomFieldsProps {
  taskId: string
  projectId: string
  /** `rows` — пары dt/dd прямо в <dl> карточки задачи (без своей секции);
   *  `mobile` — строки PropertyRow внутри мобильного блока свойств. */
  variant?: 'section' | 'rows' | 'mobile'
}

/** Renders every project field as an inline editor pre-populated from the
 *  task's stored value (if any). Owner-only field management (create/delete)
 *  lives in CustomFieldsManager (header). */
export function TaskCustomFields({
  taskId,
  projectId,
  variant = 'section',
}: TaskCustomFieldsProps) {
  const defs = useCustomFieldDefinitions(projectId)
  const values = useTaskCustomValues(taskId)
  const setValue = useSetTaskCustomValue(taskId)

  if (defs.isLoading || values.isLoading) {
    // В мобильном блоке свойств строки просто появятся, когда загрузятся:
    // спиннер между «Срок» и футером читался бы как ещё одно свойство.
    if (variant === 'mobile') return null
    return (
      <div className="flex items-center gap-2 text-[13px] text-text2">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Загружаем поля…
      </div>
    )
  }
  if (!defs.data || defs.data.length === 0) {
    return null
  }

  const byField = new Map<string, CustomFieldValue>()
  for (const v of values.data ?? []) byField.set(v.field_id, v)

  const editors = defs.data.map((def) => {
    const current = byField.get(def.id)?.value ?? null
    return {
      def,
      node: (
        <CustomFieldEditor
          definition={def}
          value={current}
          disabled={setValue.isPending}
          onChange={(next) => setValue.mutate({ fieldId: def.id, value: next })}
          variant={variant === 'mobile' ? 'mobile' : 'field'}
        />
      ),
    }
  })

  if (variant === 'mobile') {
    return (
      <>
        {editors.map(({ def, node }) => (
          <PropertyRow key={def.id} label={<span className="line-clamp-1">{def.name}</span>}>
            {node}
          </PropertyRow>
        ))}
      </>
    )
  }

  // Кастом-поля живут в той же <dl>, что статус и срок: это свойства задачи,
  // а не отдельный раздел (спека редизайна).
  if (variant === 'rows') {
    return (
      <>
        {editors.map(({ def, node }) => (
          <Fragment key={def.id}>
            <dt className="flex items-center gap-[7px] text-[13px] font-semibold text-text2">
              <span className="truncate">{def.name}</span>
            </dt>
            {/* Значение, а не форма: поле не растягивается на всю панель —
                иначе три кастом-поля читаются как анкета, а не как свойства. */}
            <dd className="m-0 min-w-0 max-w-[260px]">{node}</dd>
          </Fragment>
        ))}
      </>
    )
  }

  return (
    <DrawerSection title="Поля">
      <div className="space-y-2">
        {editors.map(({ def, node }) => (
          <div key={def.id} className="grid grid-cols-[112px_1fr] items-center gap-3.5">
            <span className="truncate text-[13px] font-semibold text-text2">
              {def.name}
            </span>
            <div>{node}</div>
          </div>
        ))}
      </div>
    </DrawerSection>
  )
}
