import { Minus, Plus, Users, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import {
  useAudienceDryRun,
  useAudienceRules,
  useEmployees,
  useOrgSnapshot,
} from '@/hooks/useLearn'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { cn } from '@/lib/cn'
import { emptyRule, ORG_ROLE_LABEL, type AudienceRuleDraft } from '@/lib/learn'

export interface AudienceValue {
  is_all: boolean
  rules: AudienceRuleDraft[]
}

export const AUDIENCE_ALL: AudienceValue = { is_all: true, rules: [] }

/**
 * Черновик аудитории для диалогов контента: подтягивает СУЩЕСТВУЮЩИЕ правила
 * (ОС 2026-08-10 — раньше диалоги открывались пустыми и «затирали» настройку)
 * и сеет их в state ровно один раз. Пока `loading` — пикер не рендерить и
 * сохранение блокировать (`ready`), иначе можно записать пустую аудиторию,
 * которую не увидит никто. При ошибке загрузки `failed` — предупредить, что
 * сохранение перезапишет текущие правила.
 */
export function useAudienceDraft(audienceId: string | null): {
  value: AudienceValue
  setValue: (v: AudienceValue) => void
  loading: boolean
  failed: boolean
  ready: boolean
  extraLabels?: Record<string, string>
} {
  const rulesQ = useAudienceRules(audienceId)
  const [value, setValue] = useState<AudienceValue>({
    is_all: audienceId === null,
    rules: [],
  })
  const [seeded, setSeeded] = useState(false)

  useEffect(() => {
    if (!seeded && rulesQ.data) {
      setValue({ is_all: rulesQ.data.is_all, rules: rulesQ.data.rules })
      setSeeded(true)
    }
  }, [seeded, rulesQ.data])

  const loading = audienceId !== null && rulesQ.isLoading
  const failed = audienceId !== null && rulesQ.isError
  return {
    value,
    setValue,
    loading,
    failed,
    ready: audienceId === null || seeded || failed,
    extraLabels: rulesQ.data?.profile_labels,
  }
}

type DimensionKey = Exclude<keyof AudienceRuleDraft, 'mode'>

const DIMENSIONS: { key: DimensionKey; label: string }[] = [
  { key: 'org_roles', label: 'Контур' },
  { key: 'position_ids', label: 'Должность' },
  { key: 'position_group_ids', label: 'Группа должностей' },
  { key: 'store_ids', label: 'Магазин' },
  { key: 'store_group_ids', label: 'Группа магазинов' },
  { key: 'franchisee_ids', label: 'Франчайзи' },
  { key: 'franchisee_group_ids', label: 'Группа франчайзи' },
  { key: 'department_ids', label: 'Отдел' },
  { key: 'user_group_ids', label: 'Группа сотрудников' },
  { key: 'profile_ids', label: 'Сотрудник' },
]

/**
 * Переиспользуемый конструктор аудитории (ТЗ §18): include/exclude-строки,
 * внутри строки — И, между include-строками — ИЛИ, exclude вычитается.
 * Живой счётчик «увидят N сотрудников» через dry-run эндпоинт.
 *
 * Ф0 — используется в «Оргструктура → Доступы» как песочница; с Ф1 —
 * при публикации любого контента (controlled: value+onChange).
 */
export function AudiencePicker({
  value,
  onChange,
  extraLabels,
  className,
}: {
  value?: AudienceValue
  onChange?: (v: AudienceValue) => void
  /** Имена для чипов сверх загруженной сотни сотрудников (см. GET rules). */
  extraLabels?: Record<string, string>
  className?: string
}) {
  // Uncontrolled-режим для песочницы в админке.
  const [inner, setInner] = useState<AudienceValue>({ is_all: false, rules: [] })
  const val = value ?? inner
  const setVal = (v: AudienceValue) => {
    setInner(v)
    onChange?.(v)
  }

  const org = useOrgSnapshot()
  // Поиск в измерении «Сотрудник»: без него дропдаун молча показывал бы
  // только первую сотню активных (limit 100 в useEmployees).
  const [employeeQ, setEmployeeQ] = useState('')
  const debouncedQ = useDebouncedValue(employeeQ, 300)
  const employees = useEmployees({ status: 'active', q: debouncedQ || undefined })

  const hasEmptyInclude = val.rules.some(
    (r) => r.mode === 'include' && DIMENSIONS.every((d) => r[d.key].length === 0),
  )
  const debounced = useDebouncedValue(val, 400)
  const dryRunBody = useMemo(() => {
    if (hasEmptyInclude) return null
    return { is_all: debounced.is_all, rules: debounced.rules }
  }, [debounced, hasEmptyInclude])
  const dryRun = useAudienceDryRun(dryRunBody)

  const optionsFor = (key: DimensionKey): { id: string; label: string }[] => {
    // Контуры — статичный словарь, не зависят от загрузки справочников.
    if (key === 'org_roles') {
      return Object.entries(ORG_ROLE_LABEL).map(([id, label]) => ({ id, label }))
    }
    if (!org.data) return []
    switch (key) {
      case 'position_ids':
        return org.data.positions.filter((p) => !p.archived_at).map((p) => ({ id: p.id, label: p.name }))
      case 'position_group_ids':
        return org.data.position_groups.map((g) => ({ id: g.id, label: g.name }))
      case 'store_ids':
        return org.data.stores.filter((s) => !s.archived_at).map((s) => ({ id: s.id, label: s.name }))
      case 'store_group_ids':
        return org.data.store_groups.map((g) => ({ id: g.id, label: g.name }))
      case 'franchisee_ids':
        return org.data.franchisees.filter((f) => !f.archived_at).map((f) => ({ id: f.id, label: f.name }))
      case 'franchisee_group_ids':
        return org.data.franchisee_groups.map((g) => ({ id: g.id, label: g.name }))
      case 'department_ids':
        return org.data.departments.map((d) => ({ id: d.id, label: d.name }))
      case 'user_group_ids':
        return org.data.user_groups.map((g) => ({ id: g.id, label: g.name }))
      case 'profile_ids':
        return (employees.data?.items ?? []).map((e) => ({ id: e.id, label: e.full_name }))
    }
  }

  const labelFor = (key: DimensionKey, id: string): string =>
    optionsFor(key).find((o) => o.id === id)?.label ?? extraLabels?.[id] ?? '…'

  const updateRule = (index: number, next: AudienceRuleDraft) => {
    const rules = val.rules.map((r, i) => (i === index ? next : r))
    setVal({ ...val, rules })
  }

  const removeRule = (index: number) => {
    setVal({ ...val, rules: val.rules.filter((_, i) => i !== index) })
  }

  const includes = val.rules.filter((r) => r.mode === 'include')

  return (
    <div className={cn('space-y-3', className)}>
      <label className="flex cursor-pointer items-center gap-2 text-sm text-text">
        <input
          type="checkbox"
          checked={val.is_all && val.rules.length === 0}
          onChange={(e) =>
            setVal(e.target.checked ? { is_all: true, rules: [] } : { is_all: false, rules: [] })
          }
          className="h-4 w-4 accent-[#FFB200]"
        />
        Видно всем активным сотрудникам
      </label>

      {!(val.is_all && val.rules.length === 0) && (
        <>
          {val.rules.map((rule, i) => (
            <RuleRow
              key={i}
              rule={rule}
              optionsFor={optionsFor}
              labelFor={labelFor}
              employeeQ={employeeQ}
              onEmployeeQ={setEmployeeQ}
              onChange={(r) => updateRule(i, r)}
              onRemove={() => removeRule(i)}
            />
          ))}
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setVal({ ...val, rules: [...val.rules, emptyRule('include')] })}
            >
              <Plus className="h-3.5 w-3.5" />
              {includes.length === 0 ? 'Кому показывать' : 'ИЛИ показать также'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setVal({ ...val, rules: [...val.rules, emptyRule('exclude')] })}
            >
              <Minus className="h-3.5 w-3.5" />
              Исключить
            </Button>
          </div>
        </>
      )}

      <div className="flex items-center gap-2 rounded-lg border border-glass-border bg-surface px-3 py-2 text-sm">
        <Users className="h-4 w-4 shrink-0 text-amber" />
        {hasEmptyInclude ? (
          <span className="text-red">
            В строке «показать» не выбрано ни одного условия — добавьте условие
            или удалите строку.
          </span>
        ) : dryRun.isFetching ? (
          <span className="text-text3">Считаем…</span>
        ) : dryRun.data ? (
          <span className="text-text">
            Увидят: <b>{dryRun.data.count}</b>{' '}
            {plural(dryRun.data.count, 'сотрудник', 'сотрудника', 'сотрудников')}
            {dryRun.data.count > 0 && dryRun.data.sample.length > 0 && (
              <span className="text-text3">
                {' '}
                — {dryRun.data.sample.slice(0, 5).map((s) => s.full_name).join(', ')}
                {dryRun.data.count > 5 ? '…' : ''}
              </span>
            )}
          </span>
        ) : (
          <span className="text-text3">—</span>
        )}
      </div>
    </div>
  )
}

function RuleRow({
  rule,
  optionsFor,
  labelFor,
  employeeQ,
  onEmployeeQ,
  onChange,
  onRemove,
}: {
  rule: AudienceRuleDraft
  optionsFor: (key: DimensionKey) => { id: string; label: string }[]
  labelFor: (key: DimensionKey, id: string) => string
  employeeQ: string
  onEmployeeQ: (q: string) => void
  onChange: (r: AudienceRuleDraft) => void
  onRemove: () => void
}) {
  const [dimKey, setDimKey] = useState<DimensionKey>('position_ids')
  const [pickId, setPickId] = useState('')

  const chips: { key: DimensionKey; id: string }[] = DIMENSIONS.flatMap((d) =>
    rule[d.key].map((id) => ({ key: d.key, id })),
  )

  const addCondition = () => {
    if (!pickId) return
    if (rule[dimKey].includes(pickId)) return
    onChange({ ...rule, [dimKey]: [...rule[dimKey], pickId] })
    setPickId('')
  }

  const removeCondition = (key: DimensionKey, id: string) => {
    onChange({ ...rule, [key]: rule[key].filter((x) => x !== id) })
  }

  const available = optionsFor(dimKey).filter((o) => !rule[dimKey].includes(o.id))

  return (
    <div
      className={cn(
        'space-y-2 rounded-lg border p-3',
        rule.mode === 'include' ? 'border-glass-border bg-glass' : 'border-red/30 bg-red/5',
      )}
    >
      <div className="flex items-center justify-between">
        <span
          className={cn(
            'text-xs font-semibold uppercase tracking-wide',
            rule.mode === 'include' ? 'text-amber' : 'text-red',
          )}
        >
          {rule.mode === 'include' ? 'Показать' : 'Исключить'}
        </span>
        <button
          type="button"
          onClick={onRemove}
          aria-label="Удалить строку"
          className="rounded p-1 text-text3 hover:bg-glass hover:text-text"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {chips.map(({ key, id }, i) => (
            <span key={key + id} className="flex items-center gap-1.5">
              {/* Внутри одного измерения значения — ИЛИ (пересечение множеств),
                  «И» — только между измерениями. */}
              {i > 0 && (
                <span className="text-[10px] font-bold text-text3">
                  {chips[i - 1]?.key === key ? 'или' : 'И'}
                </span>
              )}
              <span className="flex items-center gap-1 rounded-full bg-surface px-2 py-0.5 text-xs text-text">
                <span className="text-text3">
                  {DIMENSIONS.find((d) => d.key === key)?.label}:
                </span>
                {labelFor(key, id)}
                <button
                  type="button"
                  onClick={() => removeCondition(key, id)}
                  aria-label="Убрать условие"
                  className="text-text3 hover:text-text"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Select
          className="w-44"
          value={dimKey}
          onChange={(e) => {
            setDimKey(e.target.value as DimensionKey)
            setPickId('')
          }}
        >
          {DIMENSIONS.map((d) => (
            <option key={d.key} value={d.key}>
              {d.label}
            </option>
          ))}
        </Select>
        {dimKey === 'profile_ids' && (
          <Input
            type="search"
            value={employeeQ}
            onChange={(e) => onEmployeeQ(e.target.value)}
            placeholder="Поиск сотрудника…"
            className="w-44"
          />
        )}
        <Select
          className="min-w-[160px] flex-1"
          value={pickId}
          onChange={(e) => setPickId(e.target.value)}
        >
          <option value="">Выберите…</option>
          {available.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </Select>
        <Button type="button" variant="secondary" onClick={addCondition} disabled={!pickId}>
          <Plus className="h-3.5 w-3.5" /> Условие
        </Button>
      </div>
    </div>
  )
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}
