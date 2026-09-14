import { useState } from 'react'

import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { OptionButton } from '@/components/ui/OptionButton'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { Select } from '@/components/ui/Select'
import { humanDate } from '@/lib/taskDates'
import {
  bodyFor,
  CUSTOM_UNITS,
  describeRecurrence,
  presetOf,
  RECURRENCE_PRESETS,
  type Recurrence,
  type RecurrenceFreq,
  type RecurrencePreset,
} from '@/lib/taskRecurrence'

/**
 * Выбор периодичности повтора задачи.
 *
 * Следующую дату считает СЕРВЕР и присылает в `recurrence.next_due` — до
 * сохранения показываем только формулировку правила. Второй реализации
 * календарной арифметики на клиенте нет намеренно: «каждый месяц» от 31-го
 * числа две сетки разошлись бы уже на втором шаге.
 */
export function RecurrenceDialog({
  current,
  blockedReason,
  saving,
  onSave,
  onClear,
  onClose,
}: {
  current: Recurrence | null
  /** Почему повтор недоступен (нет срока, подзадача) — текст вместо вариантов. */
  blockedReason: string | null
  saving: boolean
  onSave: (body: { freq: RecurrenceFreq; step: number }) => void
  onClear: () => void
  onClose: () => void
}) {
  const [preset, setPreset] = useState<RecurrencePreset>(presetOf(current) ?? 'week')
  const [step, setStep] = useState(String(current && current.step > 1 ? current.step : 2))
  const [unit, setUnit] = useState<Exclude<RecurrenceFreq, 'weekday'>>(
    current && current.step > 1 && current.freq !== 'weekday' ? current.freq : 'week',
  )

  const body = bodyFor(preset, Number(step), unit)
  const blocked = blockedReason !== null

  return (
    <ResponsiveDialog
      open
      onOpenChange={(v) => !v && onClose()}
      title="Повтор задачи"
      description={
        blocked
          ? undefined
          : 'Следующая задача создастся, когда вы отметите эту выполненной.'
      }
      desktopWidth={460}
      footer={
        <>
          {current && !blocked && (
            <Button type="button" variant="secondary" disabled={saving} onClick={onClear}>
              Не повторять
            </Button>
          )}
          <span className="flex-1" />
          <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
            Отмена
          </Button>
          {!blocked && (
            <Button type="button" disabled={saving} onClick={() => onSave(body)}>
              {saving ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          )}
        </>
      }
    >
      {blocked ? (
        <p className="text-[15px] leading-[1.55] text-text2">{blockedReason}</p>
      ) : (
        <div className="flex flex-col gap-4">
          <div role="radiogroup" aria-label="Периодичность" className="flex flex-wrap gap-2">
            {RECURRENCE_PRESETS.map((option) => (
              <OptionButton
                key={option.value}
                active={preset === option.value}
                disabled={saving}
                onClick={() => setPreset(option.value)}
              >
                {option.label}
              </OptionButton>
            ))}
          </div>

          {preset === 'custom' && (
            <div className="flex items-center gap-2">
              <span className="text-[15px] text-text2">каждые</span>
              <Input
                type="number"
                min={1}
                max={365}
                value={step}
                aria-label="Интервал"
                onChange={(e) => setStep(e.target.value)}
                className="h-11 w-20 lg:h-10"
              />
              <Select
                value={unit}
                aria-label="Единица интервала"
                onChange={(e) => setUnit(e.target.value as Exclude<RecurrenceFreq, 'weekday'>)}
                className="h-11 w-36 lg:h-10"
              >
                {CUSTOM_UNITS.map((u) => (
                  <option key={u.value} value={u.value}>
                    {u.label}
                  </option>
                ))}
              </Select>
            </div>
          )}

          <p className="text-[14px] text-text2">
            Повторять {describeRecurrence(body)}.
            {current && (
              <>
                {' '}
                Следующая — <span className="text-text">{humanDate(current.next_due)}</span>.
              </>
            )}
          </p>
        </div>
      )}
    </ResponsiveDialog>
  )
}
