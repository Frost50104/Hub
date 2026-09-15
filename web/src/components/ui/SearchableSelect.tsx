import { useEffect, useRef, useState } from 'react'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { SELECT_FIELD_CLASS } from '@/components/ui/Select'
import { SheetPicker } from '@/components/ui/SheetPicker'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { filterOptions, selectedLabel, type SelectOption } from '@/lib/selectOptions'

export type { SelectOption }

/** Псевдо-значение пункта «сбросить» в шторке: `SheetPicker` отдаёт только id. */
const CLEAR_ID = '__clear__'

/** От скольких вариантов показываем поиск. Для пяти магазинов это лишний клик. */
const SEARCH_THRESHOLD = 8

export interface SearchableSelectProps {
  value: string | null
  onChange: (value: string | null) => void
  options: readonly SelectOption[]
  /** Для `<Label htmlFor>`: у кнопки-триггера нет нативной связи с подписью. */
  id?: string
  disabled?: boolean
  /** Что показать, когда ничего не выбрано. По умолчанию прочерк — как у `<option value="">—</option>`. */
  placeholder?: string
  /** Подпись пункта «ничего». `null` — пункта нет (значение обязательное). */
  clearLabel?: string | null
  searchPlaceholder?: string
  emptyText?: string
  /** Заголовок нижней шторки ниже `lg`. */
  sheetTitle: string
  /**
   * Подпись выбранного, если его НЕТ в `options`.
   *
   * Формы отсеивают архивные записи, а выбранным может остаться именно
   * архивный. У пустой кнопки вид «поле не заполнено», и значение перезапишут,
   * не заметив; у нативного селекта та же дыра, но там она хотя бы старая.
   */
  currentLabel?: string | null
  /** Пункты вне фильтрации, сверху и снизу списка (см. `CreateTaskDialog`). */
  pinnedTop?: readonly SelectOption[]
  pinnedBottom?: readonly SelectOption[]
  /**
   * Классы САМОЙ кнопки — ширина, высота, `flex-1`.
   *
   * Один проп, а не пара «обёртка + триггер», и вешается он всегда через `cn`.
   * Иначе ширину пришлось бы передавать в `DropdownMenuTrigger`, а тот с
   * `asChild` СКЛЕИВАЕТ className с дочерним без twMerge: `w-44` рядом с
   * `w-full` разрешался бы порядком правил в собранном CSS, а не порядком в
   * атрибуте — то есть «как повезёт».
   */
  className?: string
  /** Управляемый (обычно серверный) поиск: фильтрацию на себя берёт вызывающий. */
  searchValue?: string
  onSearchChange?: (query: string) => void
  loading?: boolean
  'aria-label'?: string
}

/**
 * Одиночный выбор с поиском.
 *
 * Нативный `<select>` не умеет искать, и на длинных списках это перестаёт быть
 * мелочью: в карточке сотрудника поле «Руководитель» предлагает 315 человек, из
 * которых руководителями реально выбраны 17 — 94% списка приходится
 * прокручивать мимо (ОС владельца 16.09).
 *
 * Раскладки ровно те же, что у «Исполнителя» в карточке задачи, и собраны из
 * готового: десктоп — `DropdownMenu` (потолок высоты и прокрутка у него уже
 * внутри), ниже `lg` — `SheetPicker` (он универсален, вне людей им пользуются
 * `StageDialogs` и `ProjectListPage`).
 *
 * Решение фильтрации живёт в `lib/selectOptions.ts` — vitest без jsdom, и
 * покрыть тестом можно только чистую функцию.
 */
export function SearchableSelect({
  value,
  onChange,
  options,
  id,
  disabled = false,
  placeholder = '—',
  clearLabel = '—',
  searchPlaceholder = 'Поиск…',
  emptyText = 'Ничего не найдено',
  sheetTitle,
  currentLabel,
  pinnedTop,
  pinnedBottom,
  className,
  searchValue,
  onSearchChange,
  loading,
  'aria-label': ariaLabel,
}: SearchableSelectProps) {
  const isDesktop = useIsDesktop()
  const [open, setOpen] = useState(false)
  const [localQuery, setLocalQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Фокус в поле поиска сразу при открытии: ради поиска список и открывают.
  // Через эффект, а не `onOpenAutoFocus` — у `DropdownMenu` этого пропа нет
  // (он есть только у голого `Menu`). Тик нужен, чтобы отработать ПОСЛЕ того,
  // как Radix сфокусирует Content, иначе фокус тут же уедет обратно.
  useEffect(() => {
    if (!open) return undefined
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => window.clearTimeout(timer)
  }, [open])

  const controlled = onSearchChange !== undefined
  const query = controlled ? (searchValue ?? '') : localQuery
  const setQuery = controlled ? onSearchChange : setLocalQuery

  // В управляемом режиме выдачу собрал вызывающий (обычно сервер) — фильтровать
  // её повторно нельзя: в ней уже нет того, что не подошло под запрос.
  const { visible, hidden } = controlled
    ? { visible: [...options], hidden: 0 }
    : filterOptions(options, query)

  const label =
    selectedLabel(options, value, currentLabel) ??
    [...(pinnedTop ?? []), ...(pinnedBottom ?? [])].find((o) => o.value === value)?.label ??
    null

  const showSearch = controlled || options.length >= SEARCH_THRESHOLD

  const pick = (next: string | null) => {
    onChange(next)
    if (!controlled) setLocalQuery('')
  }

  const trigger = (
    <button
      type="button"
      id={id}
      disabled={disabled}
      aria-label={ariaLabel}
      className={cn(
        'flex items-center text-left',
        SELECT_FIELD_CLASS,
        !label && 'text-text3',
        className,
      )}
    >
      <span className="min-w-0 flex-1 truncate">{label ?? placeholder}</span>
    </button>
  )

  if (!isDesktop) {
    const items = [
      ...(clearLabel !== null ? [{ id: CLEAR_ID, label: clearLabel, selected: !value }] : []),
      ...(pinnedTop ?? []).map((o) => ({ id: o.value, label: o.label, meta: o.meta, selected: o.value === value })),
      ...visible.map((o) => ({ id: o.value, label: o.label, meta: o.meta, selected: o.value === value })),
      ...(pinnedBottom ?? []).map((o) => ({ id: o.value, label: o.label, meta: o.meta, selected: o.value === value })),
    ]
    return (
      <>
        <div className="contents" onClick={() => !disabled && setOpen(true)}>
          {trigger}
        </div>
        <SheetPicker
          open={open}
          onOpenChange={setOpen}
          title={sheetTitle}
          description={hidden > 0 ? `Показаны первые ${visible.length} из ${visible.length + hidden}` : undefined}
          items={items}
          onSelect={(picked) => pick(picked === CLEAR_ID ? null : picked)}
          searchable={showSearch}
          searchPlaceholder={searchPlaceholder}
          {...(controlled ? { searchValue: query, onSearchChange: setQuery } : {})}
          loading={loading}
          emptyText={emptyText}
        />
      </>
    )
  }

  const renderItem = (option: SelectOption) => (
    <DropdownMenuItem key={option.value} onSelect={() => pick(option.value)}>
      <span className="min-w-0 flex-1 truncate">{option.label}</span>
      {option.meta && <span className="ml-2 shrink-0 text-[12px] text-text3">{option.meta}</span>}
    </DropdownMenuItem>
  )

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild disabled={disabled}>
        {trigger}
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="w-[var(--radix-dropdown-menu-trigger-width)] min-w-[220px]"
      >
        {showSearch && (
          /* sticky: у Content есть потолок высоты и прокрутка, иначе поле
             уезжает за верхний край меню на первом же движении. */
          <div className="sticky top-0 z-10 bg-bg-alt px-2 py-1">
            <input
              ref={inputRef}
              type="text"
              placeholder={searchPlaceholder}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              // ОБЯЗАТЕЛЬНО. Radix Menu вешает typeahead на Content и считает
              // «внутренним» любой keydown, включая набранный в этом поле:
              // после первой же совпавшей буквы он делает `newItem.focus()` и
              // забирает фокус, так что второй символ уходит в меню. Замер
              // 16.09 на стенде: без этой строки фокус уезжал с INPUT на
              // «Пётр Попов» с первого символа. Escape не страдает — его Radix
              // ловит на document в фазе ЗАХВАТА.
              onKeyDown={(e) => e.stopPropagation()}
              className="w-full rounded border border-glass-border bg-glass px-2 py-1 text-sm text-text placeholder:text-text3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            />
          </div>
        )}

        {clearLabel !== null && (
          <DropdownMenuItem onSelect={() => pick(null)}>{clearLabel}</DropdownMenuItem>
        )}
        {(pinnedTop ?? []).map(renderItem)}
        {visible.length === 0 && (
          <div className="px-2 py-1.5 text-[13px] text-text2">
            {loading ? 'Ищем…' : emptyText}
          </div>
        )}
        {visible.map(renderItem)}
        {hidden > 0 && (
          <div className="px-2 py-1.5 text-[12px] text-text3">
            Показаны первые {visible.length} из {visible.length + hidden} — уточните поиск
          </div>
        )}
        {(pinnedBottom ?? []).map(renderItem)}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
