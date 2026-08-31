import { employeeTruncationNote } from '@/lib/employeeList'

/**
 * «Показаны N из M» под списком выбора сотрудников.
 *
 * Отдельным компонентом, потому что мест четыре — пикер руководителя, цели
 * привязки, состав группы, аудитории, — и правило «показано не всё» обязано
 * быть одним. Именно так этот баг и жил: обрезку заметили в `AudiencePicker`,
 * прикрыли поиском на месте, и в остальные пять мест знание не доехало.
 *
 * При полном списке не рисует ничего: под дропдауном «Всего: 149» — шум.
 */
export function EmployeeListNote({
  data,
}: {
  data?: { items: unknown[]; total: number }
}) {
  const note = data ? employeeTruncationNote(data.items.length, data.total) : null
  if (!note) return null
  return <p className="mt-1 text-xs text-text3">{note}</p>
}
