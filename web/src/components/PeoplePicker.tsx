import { Check, ChevronDown, UserRound } from 'lucide-react'
import { useState, type ButtonHTMLAttributes } from 'react'

import { Avatar } from '@/components/ui/Avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { SheetPicker } from '@/components/ui/SheetPicker'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useTenantMembers } from '@/hooks/useTenantMembers'
import { cn } from '@/lib/cn'

/** Псевдо-id пункта «Очистить» в шторке: настоящих id-пустышек там нет. */
const CLEAR_ID = '__clear__'

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
  /** Заголовок мобильной шторки. */
  sheetTitle?: string
  /**
   * `filter` — компактный комбобокс тулбара: 32px, 12/500, в один ряд с
   * нативными селектами фильтров (у них общая геометрия SELECT_CLASS).
   */
  variant?: 'field' | 'filter'
}

/**
 * Поиск и выбор сотрудника tenant'а (дебаунс — внутри useTenantMembers).
 * Список ограничен shadow_users — теми, кто хотя бы раз заходил в Hub.
 *
 * Раскладок две, как у `PeoplePickerMulti`: от `lg` — выпадашка, ниже —
 * нижняя шторка (решение владельца 15.09 после ОС «список имён не
 * скроллится»).
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
  sheetTitle = 'Выберите человека',
  variant = 'field',
}: PeoplePickerProps) {
  const isDesktop = useIsDesktop()
  const [sheetOpen, setSheetOpen] = useState(false)
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

  // Одна кнопка на обе раскладки: на десктопе её забирает
  // DropdownMenuTrigger, на телефоне она открывает шторку.
  const trigger = (props: ButtonHTMLAttributes<HTMLButtonElement>) => (
        <button
          type="button"
          disabled={disabled}
          className={cn(
            isFilter
              ? 'inline-flex h-8 shrink-0 items-center gap-[7px] whitespace-nowrap rounded-md border border-glass-border bg-glass px-2.5 text-[12px] font-medium text-text2 hover:bg-surface focus-visible:border-amber focus-visible:outline-none'
              : cn(TRIGGER_CLASS, 'flex items-center justify-between gap-2 text-left'),
            disabled && 'cursor-not-allowed opacity-60',
          )}
          {...props}
        >
          <div className="flex min-w-0 items-center gap-2">
            {value ? (
              <Avatar
                employeeId={value}
                name={label}
                email={email}
                className="h-5 w-5 text-[12px]"
              />
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
  )

  if (!isDesktop) {
    return (
      <>
        {trigger({ onClick: () => !disabled && setSheetOpen(true) })}
        <SheetPicker
          open={sheetOpen}
          onOpenChange={setSheetOpen}
          title={sheetTitle}
          searchable
          searchPlaceholder="Фамилия или имя…"
          searchValue={query}
          onSearchChange={setQuery}
          loading={members.isFetching}
          emptyText="Никого не нашли"
          items={[
            ...options.map((m) => ({
              id: m.employee_id,
              label: m.full_name || m.email || m.employee_id,
              // Почта различает полных тёзок — на проде таких две пары.
              meta: m.email || undefined,
              selected: m.employee_id === value,
              icon: (
                <Avatar
                  employeeId={m.employee_id}
                  name={m.full_name}
                  email={m.email}
                  className="h-8 w-8 text-[13px]"
                />
              ),
            })),
            ...(allowClear && value
              ? [{ id: CLEAR_ID, label: 'Очистить' }]
              : []),
          ]}
          onSelect={(id) => onChange(id === CLEAR_ID ? null : id)}
        />
      </>
    )
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        {trigger({})}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[260px]">
        {/* sticky: у Content появился потолок высоты и прокрутка, иначе поиск
            уезжает за верхний край меню на первом же движении. */}
        <div className="sticky top-0 z-10 bg-bg-alt px-2 py-1">
          <input
            type="text"
            placeholder="Поиск…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded border border-glass-border bg-glass px-2 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
          />
        </div>
        {options.length === 0 && (
          <div className="px-2 py-1.5 text-[13px] text-text2">
            {members.isFetching ? 'Ищем…' : 'Никого не нашли'}
          </div>
        )}
        {options.map((m) => (
          <DropdownMenuItem
            key={m.employee_id}
            onSelect={() => onChange(m.employee_id)}
          >
            <Avatar
              employeeId={m.employee_id}
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
