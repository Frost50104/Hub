import { Check, ChevronDown } from 'lucide-react'
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
import { type CustomFieldDefinition } from '@/lib/customFields'

interface CustomFieldEditorProps {
  definition: CustomFieldDefinition
  value: unknown
  /** Called with the new JSON-serialisable value, or `null` to clear. */
  onChange: (next: unknown) => void
  disabled?: boolean
}

const INPUT_CLASS =
  'w-full rounded-md border border-glass-border bg-glass px-2 py-1 text-sm text-text placeholder:text-text3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60'

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
}: CustomFieldEditorProps) {
  switch (definition.type) {
    case 'text':
      return <TextEditor value={value} onChange={onChange} disabled={disabled} />
    case 'number':
      return <NumberEditor value={value} onChange={onChange} disabled={disabled} />
    case 'date':
      return <DateEditor value={value} onChange={onChange} disabled={disabled} />
    case 'select':
      return (
        <SelectEditor
          definition={definition}
          value={value}
          onChange={onChange}
          disabled={disabled}
        />
      )
    case 'multi_select':
      return (
        <MultiSelectEditor
          definition={definition}
          value={value}
          onChange={onChange}
          disabled={disabled}
        />
      )
    case 'person':
      return <PersonEditor value={value} onChange={onChange} disabled={disabled} />
    case 'checkbox':
      return <CheckboxEditor value={value} onChange={onChange} disabled={disabled} />
  }
}

function TextEditor({
  value,
  onChange,
  disabled,
}: {
  value: unknown
  onChange: (v: unknown) => void
  disabled?: boolean
}) {
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
      className={INPUT_CLASS}
    />
  )
}

function NumberEditor({
  value,
  onChange,
  disabled,
}: {
  value: unknown
  onChange: (v: unknown) => void
  disabled?: boolean
}) {
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
      className={INPUT_CLASS}
    />
  )
}

function DateEditor({
  value,
  onChange,
  disabled,
}: {
  value: unknown
  onChange: (v: unknown) => void
  disabled?: boolean
}) {
  const str = typeof value === 'string' ? value : ''
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
}: CustomFieldEditorProps) {
  const current = definition.options.find(
    (opt) => opt.id === (typeof value === 'string' ? value : ''),
  )
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button
          type="button"
          className={cn(
            INPUT_CLASS,
            'flex items-center justify-between text-left',
          )}
        >
          <span className={cn(current ? 'text-text' : 'text-text3')}>
            {current?.label ?? '—'}
          </span>
          <ChevronDown className="h-3.5 w-3.5 opacity-60" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[240px]">
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
}: CustomFieldEditorProps) {
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
          className={cn(
            INPUT_CLASS,
            'flex items-center justify-between gap-2 text-left',
          )}
        >
          <span
            className={cn(
              'truncate',
              labels.length ? 'text-text' : 'text-text3',
            )}
          >
            {labels.length ? labels.join(', ') : '—'}
          </span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[240px]">
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

function PersonEditor({
  value,
  onChange,
  disabled,
}: {
  value: unknown
  onChange: (v: unknown) => void
  disabled?: boolean
}) {
  const [query, setQuery] = useState('')
  const members = useTenantMembers(query)
  const currentId = typeof value === 'string' ? value : null
  const current = members.data?.find((m) => m.employee_id === currentId)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button
          type="button"
          className={cn(
            INPUT_CLASS,
            'flex items-center justify-between gap-2 text-left',
          )}
        >
          <div className="flex min-w-0 items-center gap-2">
            {current && (
              <Avatar
                name={current.full_name}
                email={current.email}
                className="h-5 w-5 text-[9px]"
              />
            )}
            <span
              className={cn(
                'truncate',
                current ? 'text-text' : 'text-text3',
              )}
            >
              {current
                ? current.full_name || current.email || current.employee_id
                : '—'}
            </span>
          </div>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />
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
        {members.data?.length === 0 && (
          <div className="px-2 py-1.5 text-xs text-text3">Никого не нашли</div>
        )}
        {members.data?.map((m) => (
          <DropdownMenuItem
            key={m.employee_id}
            onSelect={() => onChange(m.employee_id)}
          >
            <Avatar
              name={m.full_name}
              email={m.email}
              className="mr-2 h-5 w-5 text-[9px]"
            />
            <span className="flex-1 truncate">
              {m.full_name || m.email || m.employee_id}
            </span>
            {m.employee_id === currentId && <Check className="h-3.5 w-3.5" />}
          </DropdownMenuItem>
        ))}
        {currentId && (
          <DropdownMenuItem onSelect={() => onChange(null)}>
            Очистить
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function CheckboxEditor({
  value,
  onChange,
  disabled,
}: {
  value: unknown
  onChange: (v: unknown) => void
  disabled?: boolean
}) {
  const checked = value === true
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
