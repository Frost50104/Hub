/**
 * Почему аудитория пустая — объяснение вместо молчаливого «Увидят: 0».
 *
 * ОС 2026-08-24: тестировщица выбирала должность «Администратор», получала
 * ноль и не могла понять причину — должность просто никому не проставлена
 * (на проде из 11 активных сотрудников должность есть у двух). Пикер обязан
 * называть виновное условие, а не просто показывать ноль.
 *
 * Чистая функция ради vitest: jsdom в проекте нет, компонент протестировать
 * нечем.
 */

/** `{измерение: {значение: сколько сотрудников}}`; значения без людей опущены. */
export type DimensionCounts = Record<string, Record<string, number>>

export interface PickedCondition {
  /** Ключ измерения (`position_ids`, `org_roles`, …). */
  key: string
  /** Значение: id справочника или код контура. */
  id: string
  /** «Должность», «Магазин» — для текста подсказки. */
  dimensionLabel: string
  /** «Администратор» — для текста подсказки. */
  valueLabel: string
}

export type EmptyReason =
  | { kind: 'value'; dimensionLabel: string; valueLabels: string[] }
  | { kind: 'intersection'; dimensionLabels: string[] }

/**
 * Разобрать, почему строка правила никого не находит.
 *
 * - `value` — целое измерение пустое: ни за одним выбранным значением нет
 *   сотрудников (типичный случай — незаполненные должности);
 * - `intersection` — по отдельности люди есть, но одновременно всем условиям
 *   строки не отвечает никто (измерения внутри строки соединены И);
 * - `null` — объяснить нечем: условий нет либо счётчики ещё не загрузились.
 *
 * `profile_ids` («конкретный сотрудник») в разборе не участвует: счётчик у
 * человека всегда 1 и виноватым он быть не может.
 */
export function emptyPickReason(
  picked: readonly PickedCondition[],
  counts: DimensionCounts | undefined,
): EmptyReason | null {
  if (!counts || picked.length === 0) return null

  const byDimension = new Map<string, PickedCondition[]>()
  for (const c of picked) {
    if (c.key === 'profile_ids') continue
    const list = byDimension.get(c.key) ?? []
    list.push(c)
    byDimension.set(c.key, list)
  }
  if (byDimension.size === 0) return null

  for (const [key, conditions] of byDimension) {
    const total = conditions.reduce((sum, c) => sum + (counts[key]?.[c.id] ?? 0), 0)
    if (total === 0) {
      return {
        kind: 'value',
        dimensionLabel: conditions[0]!.dimensionLabel,
        valueLabels: conditions.map((c) => c.valueLabel),
      }
    }
  }

  // Каждое измерение по отдельности кого-то находит — виновато пересечение.
  if (byDimension.size < 2) return null
  return {
    kind: 'intersection',
    dimensionLabels: [...byDimension.values()].map((c) => c[0]!.dimensionLabel),
  }
}

/** Текст подсказки под счётчиком «Увидят: 0». Формулировки нейтральны по роду:
 *  измерения бывают и мужского, и женского («магазин», «должность»). */
export function emptyPickText(reason: EmptyReason): string {
  if (reason.kind === 'value') {
    const values = reason.valueLabels.map((v) => `«${v}»`).join(', ')
    return `Ни один активный сотрудник не подходит: ${reason.dimensionLabel} — ${values}.`
  }
  const dims = reason.dimensionLabels.map((d) => d.toLowerCase()).join(' и ')
  return `Нет сотрудников, у которых одновременно совпадают ${dims}.`
}
