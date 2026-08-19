import { Check, ChevronDown, Plus, X } from 'lucide-react'
import { useState } from 'react'

import { AvatarStack } from '@/components/ui/AvatarStack'
import { Avatar } from '@/components/ui/Avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { useTenantMembers } from '@/hooks/useTenantMembers'
import { cn } from '@/lib/cn'
import { type TaskAssigneeBrief } from '@/lib/tasks'

const TRIGGER_CLASS =
  'w-full rounded-md border border-glass-border bg-glass px-2 py-1 text-sm text-text placeholder:text-text2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60'

interface PeoplePickerMultiProps {
  /** ПОЛНЫЕ brief'ы, а не id: наверх тоже отдаём brief, чтобы вызывающий мог
   *  оптимистично обновить кэш без похода в справочник сотрудников. */
  value: TaskAssigneeBrief[]
  /** Вызывается на каждый тоггл: (человек, стал ли он выбран). */
  onToggle: (person: TaskAssigneeBrief, next: boolean) => void
  /** Снять всех разом. Отдельно от onToggle: цикл по нему слал N параллельных
   *  запросов, которые затирали друг другу оптимистичный кэш (onError любого
   *  откатывал список целиком) и разъезжались на записи зеркала. */
  onClearAll: () => void
  disabled?: boolean
  /** Потолок; зеркалит MAX_ASSIGNEES на бэкенде. */
  max?: number
  placeholder?: string
  /**
   * `chips` — раскладка карточки задачи: исполнители чипами с крестиком,
   * добавление пунктирной кнопкой. `field` — компактный триггер для строк.
   */
  variant?: 'field' | 'chips'
}

function label(p: TaskAssigneeBrief): string {
  return p.full_name || p.email || p.employee_id
}

/**
 * Мультивыбор исполнителей.
 *
 * Отдельный компонент, а не проп `multiple` у PeoplePicker: под TS strict
 * union-пропсы `string | null | string[]` потребовали бы кастов в каждом
 * существующем вызове, а триггер здесь принципиально другой (стек аватаров
 * вместо одного).
 */
export function PeoplePickerMulti({
  value,
  onToggle,
  onClearAll,
  disabled,
  max = 10,
  placeholder = 'Не назначен',
  variant = 'field',
}: PeoplePickerMultiProps) {
  const [query, setQuery] = useState('')
  // Лимит выше дефолтного (10): в мультивыборе список — рабочая поверхность,
  // а не разовый выбор.
  const members = useTenantMembers(query, 25)

  const selectedIds = new Set(value.map((p) => p.employee_id))
  // Выбранные показываем ВСЕГДА, даже если не попали в выдачу поиска —
  // иначе снять человека можно было бы только найдя его.
  const found = (members.data ?? []).filter((m) => !selectedIds.has(m.employee_id))
  const options: TaskAssigneeBrief[] = [
    ...value,
    ...found.map((m) => ({
      employee_id: m.employee_id,
      email: m.email,
      full_name: m.full_name,
    })),
  ]
  const atMax = value.length >= max

  const chips = variant === 'chips'

  const triggerText =
    value.length === 0
      ? placeholder
      : value.length === 1
        ? label(value[0]!)
        : `${value.length} исполнителей`

  return (
    <DropdownMenu>
      {chips ? (
        // Карточка задачи: каждый исполнитель — чип с крестиком, добавление —
        // пунктирная кнопка. Стек аватаров под выпадашкой там не читается:
        // в карточке есть место назвать людей по именам.
        <span className="flex flex-wrap items-center gap-2">
          {value.map((p) => (
            <span
              key={p.employee_id}
              className="inline-flex h-8 items-center gap-[7px] rounded-full border border-glass-border py-0 pl-1 pr-2.5 text-[14px] font-medium text-text"
            >
              <Avatar name={p.full_name} email={p.email} className="h-6 w-6" />
              <span className="max-w-[180px] truncate">{label(p)}</span>
              {!disabled && (
                <button
                  type="button"
                  onClick={() => onToggle(p, false)}
                  aria-label={`Снять исполнителя ${label(p)}`}
                  className="-mr-1.5 flex h-5 w-5 items-center justify-center rounded-full text-text2 hover:text-text"
                >
                  <X className="h-3 w-3" strokeWidth={2.4} />
                </button>
              )}
            </span>
          ))}
          {!disabled && (
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="inline-flex h-8 items-center gap-1.5 rounded-full border border-dashed border-glass-border px-3 text-[14px] font-semibold text-text2 hover:border-amber hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              >
                <Plus className="h-3.5 w-3.5" strokeWidth={2.2} /> Добавить
              </button>
            </DropdownMenuTrigger>
          )}
          {disabled && value.length === 0 && (
            <span className="text-[14px] text-text2">Не назначен</span>
          )}
        </span>
      ) : (
        <DropdownMenuTrigger asChild disabled={disabled}>
          <button
            type="button"
            className={cn(
              TRIGGER_CLASS,
              'flex items-center justify-between gap-2 text-left',
              disabled && 'cursor-not-allowed opacity-60',
            )}
          >
            <div className="flex min-w-0 items-center gap-2">
              {value.length > 0 && <AvatarStack people={value} max={3} />}
              <span
                className={cn('truncate', value.length ? 'text-text' : 'text-text2')}
              >
                {triggerText}
              </span>
            </div>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />
          </button>
        </DropdownMenuTrigger>
      )}
      <DropdownMenuContent align="start" className="w-[280px]">
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
        {options.map((m) => {
          const selected = selectedIds.has(m.employee_id)
          return (
            <DropdownMenuItem
              key={m.employee_id}
              disabled={!selected && atMax}
              // Без preventDefault Radix закрывает меню на каждом клике —
              // выбрать нескольких подряд стало бы невозможно.
              onSelect={(e) => {
                e.preventDefault()
                onToggle(m, !selected)
              }}
            >
              <Avatar
                name={m.full_name}
                email={m.email}
                className="mr-2 h-5 w-5 text-[12px]"
              />
              <span className="flex-1 truncate">{label(m)}</span>
              {selected && <Check className="h-3.5 w-3.5" />}
            </DropdownMenuItem>
          )
        })}
        {atMax && (
          <div className="px-2 py-1.5 text-[13px] text-text2">
            Максимум {max} исполнителей
          </div>
        )}
        {value.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={(e) => {
                e.preventDefault()
                onClearAll()
              }}
            >
              Очистить всех
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
