import {
  type CustomFieldDefinition,
  type CustomFieldType,
} from './customFields'

/**
 * Render-only formatter for a custom-field value in compact contexts
 * (List view columns, future report tables). Inline editing is reserved
 * for `CustomFieldEditor`.
 */
export function formatCustomFieldValue(
  definition: CustomFieldDefinition,
  value: unknown,
): string {
  if (value === null || value === undefined || value === '') return '—'

  const t: CustomFieldType = definition.type
  switch (t) {
    case 'text':
      return typeof value === 'string' ? value : String(value)
    case 'number':
      return typeof value === 'number'
        ? Number.isInteger(value)
          ? String(value)
          : value.toFixed(2)
        : String(value)
    case 'date': {
      if (typeof value !== 'string') return '—'
      try {
        return new Date(value + 'T00:00:00').toLocaleDateString('ru-RU', {
          day: 'numeric',
          month: 'short',
          year: 'numeric',
        })
      } catch {
        return value
      }
    }
    case 'select': {
      const opt = definition.options.find((o) => o.id === value)
      return opt?.label ?? '—'
    }
    case 'multi_select': {
      if (!Array.isArray(value)) return '—'
      const labels = definition.options
        .filter((o) => value.includes(o.id))
        .map((o) => o.label)
      return labels.length ? labels.join(', ') : '—'
    }
    case 'person':
      // We don't have an easy way to look up shadow_users from a sync formatter.
      // Drawer-side editor resolves to the full picker. In the table we show
      // a short UUID prefix — visual hint that someone is assigned.
      return typeof value === 'string' ? value.slice(0, 8) : '—'
    case 'checkbox':
      return value === true ? '✓' : '—'
  }
}
