import { Check, ChevronDown } from 'lucide-react'
import { useState } from 'react'

import { PeoplePicker } from '@/components/PeoplePicker'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { Switch } from '@/components/ui/Switch'
import { MobileDateCell } from '@/components/ui/MobileDateCell'
import { cn } from '@/lib/cn'
import { type CustomFieldDefinition } from '@/lib/customFields'

type EditorVariant = 'field' | 'mobile'

interface CustomFieldEditorProps {
  definition: CustomFieldDefinition
  value: unknown
  /** Called with the new JSON-serialisable value, or `null` to clear. */
  onChange: (next: unknown) => void
  disabled?: boolean
  /**
   * `mobile` — контрол ПРАВОЙ части PropertyRow (48px): без рамки, 16px,
   * выравнивание вправо, чекбокс — тумблер 44×24 в тап-цели 44×44.
   */
  variant?: EditorVariant
}

const INPUT_CLASS =
  'w-full rounded-md border border-glass-border bg-glass px-2 py-1 text-sm text-text placeholder:text-text2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60'
/** Та же геометрия, что у MOBILE_CONTROL карточки задачи (Этап/Приоритет/Срок). */
const MOBILE_INPUT =
  'min-h-[46px] w-full max-w-full appearance-none bg-transparent pr-2.5 text-right font-body text-[16px] text-text placeholder:text-text2 focus-visible:outline-none disabled:opacity-100'
const MOBILE_TRIGGER =
  'inline-flex min-h-[46px] max-w-full items-center justify-end gap-1.5 bg-transparent pr-2.5 text-right font-body text-[16px] focus-visible:outline-none'

/**
 * Inline editor for one (definition, value) pair. Type-switch:
 * - text/number → `<input>` with onBlur commit.
 * - date → `<input type="date">`, commit on change.
 * - select/multi_select → DropdownMenu with options (single vs multi check).
 * - person → searchable TenantMembers picker (debounced).
 * - checkbox → toggle.
 *
 * Pure presentation — the parent owns the mutation. Value shape matches
 * `app/services/custom_field_validator.py` storage forms.
 */
export function CustomFieldEditor({
  definition,
  value,
  onChange,
  disabled,
  variant = 'field',
}: CustomFieldEditorProps) {
  switch (definition.type) {
    case 'text':
      return <TextEditor value={value} onChange={onChange} disabled={disabled} variant={variant} />
    case 'number':
      return <NumberEditor value={value} onChange={onChange} disabled={disabled} variant={variant} />
    case 'date':
      return (
        <DateEditor
          value={value}
          onChange={onChange}
          disabled={disabled}
          variant={variant}
          label={definition.name}
        />
      )
    case 'select':
      return (
        <SelectEditor
          definition={definition}
          value={value}
          onChange={onChange}
          disabled={disabled}
          variant={variant}
        />
      )
    case 'multi_select':
      return (
        <MultiSelectEditor
          definition={definition}
          value={value}
          onChange={onChange}
          disabled={disabled}
          variant={variant}
        />
      )
    case 'person':
      return <PersonEditor value={value} onChange={onChange} disabled={disabled} variant={variant} />
    case 'checkbox':
      return <CheckboxEditor value={value} onChange={onChange} disabled={disabled} variant={variant} />
  }
}

interface ScalarEditorProps {
  value: unknown
  onChange: (v: unknown) => void
  disabled?: boolean
  variant: EditorVariant
  /** Имя поля — подпись контрола для скринридера (у даты своей нет). */
  label?: string
}

function TextEditor({ value, onChange, disabled, variant }: ScalarEditorProps) {
  const [draft, setDraft] = useState(typeof value === 'string' ? value : '')
  return (
    <input
      type="text"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        const trimmed = draft.trim()
        if (trimmed === (typeof value === 'string' ? value : '')) return
        onChange(trimmed || null)
      }}
      disabled={disabled}
      placeholder="—"
      className={variant === 'mobile' ? MOBILE_INPUT : INPUT_CLASS}
    />
  )
}

function NumberEditor({ value, onChange, disabled, variant }: ScalarEditorProps) {
  const [draft, setDraft] = useState(
    typeof value === 'number' ? String(value) : '',
  )
  return (
    <input
      type="number"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        if (draft.trim() === '') {
          if (value !== null && value !== undefined) onChange(null)
          return
        }
        const num = Number(draft)
        if (!Number.isFinite(num)) return
        if (num !== value) onChange(num)
      }}
      disabled={disabled}
      placeholder="—"
      className={variant === 'mobile' ? MOBILE_INPUT : INPUT_CLASS}
    />
  )
}

function DateEditor({ value, onChange, disabled, variant, label }: ScalarEditorProps) {
  const str = typeof value === 'string' ? value : ''
  // На мобилке — тот же приём, что у «Старта» и «Срока» карточки: общий
  // `MOBILE_INPUT` содержит `appearance-none`, из-за которого пустое поле даты
  // на WebKit не показывало ничего и не тапалось (ОС 27.08). Кастом-поле типа
  // «дата» — то же поле, просто до него ещё не дошли жалобой.
  if (variant === 'mobile') {
    return (
      <MobileDateCell
        value={str}
        ariaLabel={label ?? 'Дата'}
        readOnly={Boolean(disabled)}
        onChange={(v) => onChange(v || null)}
      />
    )
  }
  return (
    <input
      type="date"
      value={str}
      onChange={(e) => {
        const next = e.target.value
        onChange(next || null)
      }}
      disabled={disabled}
      className={INPUT_CLASS}
    />
  )
}

function SelectEditor({
  definition,
  value,
  onChange,
  disabled,
  variant = 'field',
}: CustomFieldEditorProps) {
  const mobile = variant === 'mobile'
  const current = definition.options.find(
    (opt) => opt.id === (typeof value === 'string' ? value : ''),
  )
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button
          type="button"
          className={
            mobile ? MOBILE_TRIGGER : cn(INPUT_CLASS, 'flex items-center justify-between text-left')
          }
        >
          <span className={cn('truncate', current ? 'text-text' : 'text-text2')}>
            {current?.label ?? '—'}
          </span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={mobile ? 'end' : 'start'} className="w-[240px]">
        {definition.options.map((opt) => (
          <DropdownMenuItem
            key={opt.id}
            onSelect={() => onChange(opt.id)}
          >
            {opt.id === current?.id && <Check className="mr-2 h-3.5 w-3.5" />}
            {opt.label}
          </DropdownMenuItem>
        ))}
        {current && (
          <DropdownMenuItem onSelect={() => onChange(null)}>
            Очистить
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function MultiSelectEditor({
  definition,
  value,
  onChange,
  disabled,
  variant = 'field',
}: CustomFieldEditorProps) {
  const mobile = variant === 'mobile'
  const selected: string[] = Array.isArray(value)
    ? (value.filter((v): v is string => typeof v === 'string'))
    : []
  const selectedSet = new Set(selected)
  const labels = definition.options
    .filter((o) => selectedSet.has(o.id))
    .map((o) => o.label)

  const toggle = (id: string) => {
    const next = selectedSet.has(id)
      ? selected.filter((s) => s !== id)
      : [...selected, id]
    onChange(next)
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button
          type="button"
          className={
            mobile
              ? MOBILE_TRIGGER
              : cn(INPUT_CLASS, 'flex items-center justify-between gap-2 text-left')
          }
        >
          <span
            className={cn(
              'truncate',
              labels.length ? 'text-text' : 'text-text2',
            )}
          >
            {labels.length ? labels.join(', ') : '—'}
          </span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={mobile ? 'end' : 'start'} className="w-[240px]">
        {definition.options.map((opt) => (
          <DropdownMenuItem
            key={opt.id}
            onSelect={(e) => {
              e.preventDefault()
              toggle(opt.id)
            }}
          >
            {selectedSet.has(opt.id) && <Check className="mr-2 h-3.5 w-3.5" />}
            {opt.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function PersonEditor({ value, onChange, disabled, variant }: ScalarEditorProps) {
  const currentId = typeof value === 'string' ? value : null
  const picker = (
    <PeoplePicker
      value={currentId}
      onChange={(id) => onChange(id)}
      disabled={disabled}
    />
  )
  if (variant !== 'mobile') return picker
  // Тот же пикер (поиск по сотрудникам), но как значение-кнопка справа:
  // рамку и фон поля снимаем селектором обёртки.
  return (
    <span className="flex w-full min-w-0 justify-end [&>button]:min-h-[46px] [&>button]:w-auto [&>button]:max-w-full [&>button]:justify-end [&>button]:border-0 [&>button]:bg-transparent [&>button]:px-0 [&>button]:pr-2.5 [&>button]:text-[16px] [&>button]:shadow-none">
      {picker}
    </span>
  )
}

function CheckboxEditor({ value, onChange, disabled, variant }: ScalarEditorProps) {
  const checked = value === true
  if (variant === 'mobile') {
    return (
      <span className="-mr-1 flex h-11 w-11 items-center justify-center">
        <Switch
          checked={checked}
          disabled={disabled}
          onCheckedChange={(next) => onChange(next)}
        />
      </span>
    )
  }
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      disabled={disabled}
      role="checkbox"
      aria-checked={checked}
      className={cn(
        'inline-flex h-6 w-6 items-center justify-center rounded border border-glass-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
        checked ? 'bg-amber text-on-amber' : 'bg-glass text-transparent',
      )}
    >
      <Check className="h-3.5 w-3.5" />
    </button>
  )
}
