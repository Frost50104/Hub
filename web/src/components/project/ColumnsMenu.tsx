import { Check, Columns3 } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { useCustomFieldDefinitions } from '@/hooks/useCustomFields'
import { useViewConfig } from '@/stores/viewConfig'

interface ColumnsMenuProps {
  projectId: string
}

/**
 * Toggle visibility for custom-field columns in the List view.
 * Persisted per-project in localStorage via `useViewConfig` zustand store.
 */
export function ColumnsMenu({ projectId }: ColumnsMenuProps) {
  const defs = useCustomFieldDefinitions(projectId)
  const visible = useViewConfig((s) => s.byProject[projectId]?.visibleCustomFields ?? [])
  const toggle = useViewConfig((s) => s.toggleCustomField)

  if (defs.data?.length === 0) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="secondary" size="sm" aria-label="Колонки">
          <Columns3 className="h-3.5 w-3.5" />
          Колонки
          {visible.length > 0 && (
            <span className="ml-1 text-xs text-text3">({visible.length})</span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[220px]">
        <DropdownMenuLabel className="text-[10px] uppercase tracking-wider text-text3">
          Кастом-поля
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {defs.isError && (
          <p className="px-2 py-1.5 text-xs text-red">Не удалось загрузить поля</p>
        )}
        {defs.data?.map((d) => {
          const checked = visible.includes(d.id)
          return (
            <DropdownMenuItem
              key={d.id}
              onSelect={(e) => {
                e.preventDefault()
                toggle(projectId, d.id)
              }}
            >
              <span className="mr-2 inline-flex h-3.5 w-3.5 items-center justify-center">
                {checked && <Check className="h-3.5 w-3.5" />}
              </span>
              <span className="truncate">{d.name}</span>
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
