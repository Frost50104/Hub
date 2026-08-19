import { Check, ChevronDown, UserRound } from 'lucide-react'
import { useState } from 'react'

import { Avatar } from '@/components/ui/Avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { useTenantMembers } from '@/hooks/useTenantMembers'
import { cn } from '@/lib/cn'

const TRIGGER_CLASS =
  'w-full rounded-md border border-glass-border bg-glass px-2 py-1 text-sm text-text placeholder:text-text2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60'

interface PeoplePickerProps {
  /** employee_id выбранного человека или null. */
  value: string | null
  /** null = «Очистить». */
  onChange: (id: string | null) => void
  disabled?: boolean
  /** employee_id, которых скрыть из списка (например, уже участники). */
  excludeIds?: string[]
  /** Подпись выбранного, когда его нет в результатах поиска (напр. task.assignee). */
  currentLabel?: string | null
  /** Email выбранного — для инициалов в Avatar, когда его нет в результатах. */
  currentEmail?: string | null
  placeholder?: string
  /** Показывать пункт «Очистить» при выбранном значении. */
  allowClear?: boolean
  /**
   * `filter` — компактный комбобокс тулбара: 32px, 12/500, в один ряд с
   * нативными селектами фильтров (у них общая геометрия SELECT_CLASS).
   */
  variant?: 'field' | 'filter'
}

/**
 * Поиск и выбор сотрудника tenant'а (дебаунс — внутри useTenantMembers).
 * Список ограничен shadow_users — теми, кто хотя бы раз заходил в Hub.
 */
export function PeoplePicker({
  value,
  onChange,
  disabled,
  excludeIds,
  currentLabel,
  currentEmail,
  placeholder = '—',
  allowClear = true,
  variant = 'field',
}: PeoplePickerProps) {
  const [query, setQuery] = useState('')
  const members = useTenantMembers(query)
  const excluded = new Set(excludeIds ?? [])
  const options = (members.data ?? []).filter(
    (m) => m.employee_id === value || !excluded.has(m.employee_id),
  )
  const current = members.data?.find((m) => m.employee_id === value)
  const label =
    current?.full_name || current?.email || currentLabel || null
  const email = current?.email ?? currentEmail ?? null

  const isFilter = variant === 'filter'

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button
          type="button"
          className={cn(
            isFilter
              ? 'inline-flex h-8 shrink-0 items-center gap-[7px] whitespace-nowrap rounded-md border border-glass-border bg-glass px-2.5 text-[12px] font-medium text-text2 hover:bg-surface focus-visible:border-amber focus-visible:outline-none'
              : cn(TRIGGER_CLASS, 'flex items-center justify-between gap-2 text-left'),
            disabled && 'cursor-not-allowed opacity-60',
          )}
        >
          <div className="flex min-w-0 items-center gap-2">
            {value ? (
              <Avatar name={label} email={email} className="h-5 w-5 text-[12px]" />
            ) : (
              isFilter && (
                <span className="flex h-5 w-5 items-center justify-center rounded-full border border-dashed border-glass-border text-text2">
                  <UserRound className="h-3 w-3" strokeWidth={2} />
                </span>
              )
            )}
            <span
              className={cn(
                'truncate',
                value ? 'text-text' : isFilter ? 'text-text2' : 'text-text2',
              )}
            >
              {value ? label || value : placeholder}
            </span>
          </div>
          <ChevronDown
            className={cn('shrink-0', isFilter ? 'h-[13px] w-[13px]' : 'h-3.5 w-3.5 opacity-60')}
            strokeWidth={2.2}
          />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[260px]">
        <div className="px-2 py-1">
          <input
            type="text"
            placeholder="Поиск…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded border border-glass-border bg-glass px-2 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
          />
        </div>
        {options.length === 0 && (
          <div className="px-2 py-1.5 text-[13px] text-text2">Никого не нашли</div>
        )}
        {options.map((m) => (
          <DropdownMenuItem
            key={m.employee_id}
            onSelect={() => onChange(m.employee_id)}
          >
            <Avatar
              name={m.full_name}
              email={m.email}
              className="mr-2 h-5 w-5 text-[12px]"
            />
            <span className="flex-1 truncate">
              {m.full_name || m.email || m.employee_id}
            </span>
            {m.employee_id === value && <Check className="h-3.5 w-3.5" />}
          </DropdownMenuItem>
        ))}
        {allowClear && value && (
          <DropdownMenuItem onSelect={() => onChange(null)}>
            Очистить
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
