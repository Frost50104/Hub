import { Check, ChevronDown, Plus, X } from 'lucide-react'
import { useState, type ButtonHTMLAttributes, type ReactNode } from 'react'

import { AvatarStack } from '@/components/ui/AvatarStack'
import { Avatar } from '@/components/ui/Avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { SheetPicker } from '@/components/ui/SheetPicker'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useTenantMembers } from '@/hooks/useTenantMembers'
import { cn } from '@/lib/cn'
import { mergeSelected, personLabel } from '@/lib/peopleOptions'
import { type TaskAssigneeBrief } from '@/lib/tasks'

const TRIGGER_CLASS =
  'w-full rounded-md border border-glass-border bg-glass px-2 py-1 text-sm text-text placeholder:text-text2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60'

const ADD_CLASS =
  'inline-flex h-8 items-center gap-1.5 rounded-full border border-dashed border-glass-border px-3 text-[14px] font-semibold text-text2 hover:border-amber hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60'

interface PeoplePickerMultiProps {
  /** ПОЛНЫЕ brief'ы, а не id: наверх тоже отдаём brief, чтобы вызывающий мог
   *  оптимистично обновить кэш без похода в справочник сотрудников. */
  value: TaskAssigneeBrief[]
  /** Вызывается на каждый тоггл: (человек, стал ли он выбран). */
  onToggle: (person: TaskAssigneeBrief, next: boolean) => void
  /** Снять всех разом. Отдельно от onToggle: цикл по нему слал N параллельных
   *  запросов, которые затирали друг другу оптимистичный кэш (onError любого
   *  откатывал список целиком) и разъезжались на записи зеркала.
   *  Опционален (02.09): у наблюдателей bulk-clear ручки нет — без коллбэка
   *  пункт «Очистить всех» не рендерится. */
  onClearAll?: () => void
  disabled?: boolean
  /** Потолок; зеркалит MAX_ASSIGNEES на бэкенде. */
  max?: number
  placeholder?: string
  /** Родительный падеж мн. числа для счётчиков («исполнителей»/«наблюдателей»). */
  nounGenitivePlural?: string
  /** Префикс aria-label крестика на чипе («Снять исполнителя»). */
  removeAriaPrefix?: string
  /** Заголовок мобильной шторки («Исполнители», «Наблюдатели»). */
  sheetTitle?: string
  /**
   * `chips` — раскладка карточки задачи: исполнители чипами с крестиком,
   * добавление пунктирной кнопкой. `field` — компактный триггер для строк.
   */
  variant?: 'field' | 'chips'
}

/**
 * Мультивыбор исполнителей.
 *
 * Отдельный компонент, а не проп `multiple` у PeoplePicker: под TS strict
 * union-пропсы `string | null | string[]` потребовали бы кастов в каждом
 * существующем вызове, а триггер здесь принципиально другой (стек аватаров
 * вместо одного).
 *
 * **Раскладок две.** От `lg` — выпадашка. Ниже — нижняя шторка (`SheetPicker`,
 * решение владельца 15.09): выпадашка на 25 строк не помещалась на экран
 * телефона и, пока у неё был `overflow: hidden`, вообще не двигалась пальцем
 * (ОС 14.09 — «список имён не скроллится»). Прокрутку выпадашки починили в
 * базовом `DropdownMenuContent`, но палец на шторке всё равно удобнее: пункты
 * 52px и поиск во всю ширину.
 */
export function PeoplePickerMulti({
  value,
  onToggle,
  onClearAll,
  disabled,
  max = 10,
  placeholder = 'Не назначен',
  nounGenitivePlural = 'исполнителей',
  removeAriaPrefix = 'Снять исполнителя',
  sheetTitle = 'Исполнители',
  variant = 'field',
}: PeoplePickerMultiProps) {
  const isDesktop = useIsDesktop()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [query, setQuery] = useState('')
  // Лимит выше дефолтного (10): в мультивыборе список — рабочая поверхность,
  // а не разовый выбор.
  const members = useTenantMembers(query, 25)

  const selectedIds = new Set(value.map((p) => p.employee_id))
  // Выбранные показываем ВСЕГДА, даже если не попали в выдачу поиска —
  // иначе снять человека можно было бы только найдя его.
  const options = mergeSelected(value, members.data ?? [])
  const atMax = value.length >= max

  const chips = variant === 'chips'

  const triggerText =
    value.length === 0
      ? placeholder
      : value.length === 1
        ? personLabel(value[0]!)
        : `${value.length} ${nounGenitivePlural}`

  // Одна и та же кнопка на обе раскладки: на десктопе её забирает
  // DropdownMenuTrigger через asChild, на телефоне она открывает шторку.
  const addButton = (props: ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" className={ADD_CLASS} {...props}>
      <Plus className="h-3.5 w-3.5" strokeWidth={2.2} /> Добавить
    </button>
  )

  const fieldButton = (props: ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button
      type="button"
      disabled={disabled}
      className={cn(
        TRIGGER_CLASS,
        'flex items-center justify-between gap-2 text-left',
        disabled && 'cursor-not-allowed opacity-60',
      )}
      {...props}
    >
      <div className="flex min-w-0 items-center gap-2">
        {value.length > 0 && <AvatarStack people={value} max={3} />}
        <span className={cn('truncate', value.length ? 'text-text' : 'text-text2')}>
          {triggerText}
        </span>
      </div>
      <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />
    </button>
  )

  // Карточка задачи: каждый исполнитель — чип с крестиком, добавление —
  // пунктирная кнопка. Стек аватаров под выпадашкой там не читается:
  // в карточке есть место назвать людей по именам.
  const chipsRow = (trigger: ReactNode) => (
    <span className="flex flex-wrap items-center gap-2">
      {value.map((p) => (
        <span
          key={p.employee_id}
          className="inline-flex h-8 items-center gap-[7px] rounded-full border border-glass-border py-0 pl-1 pr-2.5 text-[14px] font-medium text-text"
        >
          <Avatar
            employeeId={p.employee_id}
            name={p.full_name}
            email={p.email}
            className="h-6 w-6"
          />
          <span className="max-w-[180px] truncate">{personLabel(p)}</span>
          {!disabled && (
            <button
              type="button"
              onClick={() => onToggle(p, false)}
              aria-label={`${removeAriaPrefix} ${personLabel(p)}`}
              className="-mr-1.5 flex h-5 w-5 items-center justify-center rounded-full text-text2 hover:text-text"
            >
              <X className="h-3 w-3" strokeWidth={2.4} />
            </button>
          )}
        </span>
      ))}
      {!disabled && trigger}
      {disabled && value.length === 0 && (
        <span className="text-[14px] text-text2">{placeholder}</span>
      )}
    </span>
  )

  if (!isDesktop) {
    return (
      <>
        {chips
          ? chipsRow(addButton({ onClick: () => setSheetOpen(true) }))
          : fieldButton({ onClick: () => !disabled && setSheetOpen(true) })}
        <SheetPicker
          open={sheetOpen}
          onOpenChange={setSheetOpen}
          title={sheetTitle}
          multi
          searchable
          searchPlaceholder="Фамилия или имя…"
          searchValue={query}
          onSearchChange={setQuery}
          loading={members.isFetching}
          emptyText="Никого не нашли"
          items={options.map((m) => ({
            id: m.employee_id,
            label: personLabel(m),
            // Почта различает полных тёзок — на проде таких две пары.
            meta: m.email || undefined,
            selected: selectedIds.has(m.employee_id),
            disabled: !selectedIds.has(m.employee_id) && atMax,
            icon: (
              <Avatar
                employeeId={m.employee_id}
                name={m.full_name}
                email={m.email}
                className="h-8 w-8 text-[13px]"
              />
            ),
          }))}
          // Шторка отдаёт только id — brief возвращаем сами: наверх ждут его
          // целиком, чтобы обновить кэш без похода в справочник.
          onSelect={(id) => {
            const person = options.find((m) => m.employee_id === id)
            if (person) onToggle(person, !selectedIds.has(id))
          }}
          footer={
            <>
              {atMax && (
                <span className="mr-auto text-[13px] text-text2">
                  Максимум {max} {nounGenitivePlural}
                </span>
              )}
              {value.length > 0 && onClearAll && (
                <button
                  type="button"
                  onClick={onClearAll}
                  className="min-h-11 rounded-md px-2 text-[15px] font-medium text-text2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                >
                  Очистить всех
                </button>
              )}
            </>
          }
        />
      </>
    )
  }

  return (
    <DropdownMenu>
      {chips ? (
        chipsRow(
          <DropdownMenuTrigger asChild>{addButton({})}</DropdownMenuTrigger>,
        )
      ) : (
        <DropdownMenuTrigger asChild disabled={disabled}>
          {fieldButton({})}
        </DropdownMenuTrigger>
      )}
      <DropdownMenuContent align="start" className="w-[280px]">
        {/* sticky: у Content появился потолок высоты и прокрутка, и без этого
            поле поиска уезжало за верхний край меню на первом же движении. */}
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
                employeeId={m.employee_id}
                name={m.full_name}
                email={m.email}
                className="mr-2 h-5 w-5 text-[12px]"
              />
              <span className="flex-1 truncate">{personLabel(m)}</span>
              {selected && <Check className="h-3.5 w-3.5" />}
            </DropdownMenuItem>
          )
        })}
        {atMax && (
          <div className="px-2 py-1.5 text-[13px] text-text2">
            Максимум {max} {nounGenitivePlural}
          </div>
        )}
        {value.length > 0 && onClearAll && (
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
