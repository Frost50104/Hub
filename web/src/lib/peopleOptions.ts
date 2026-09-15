import { type TaskAssigneeBrief } from '@/lib/tasks'
import { type TenantMember } from '@/lib/tenant'

/**
 * Список людей для пикера: выбранные сверху, найденные следом.
 *
 * Инвариант: **выбранных показываем ВСЕГДА**, даже если они не попали в
 * серверную выдачу поиска. Иначе снять человека можно было бы, только сперва
 * найдя его по фамилии — а сервер отдаёт лишь 25 строк из 227.
 *
 * Чистая функция, потому что vitest в проекте без jsdom: сам компонент не
 * покрыть, а это правило — единственное, что здесь можно проверить тестом.
 * Ею же пользуются обе раскладки (выпадашка на десктопе и шторка на
 * телефоне), чтобы список не разъехался между ними.
 */
export function mergeSelected(
  value: TaskAssigneeBrief[],
  found: TenantMember[],
): TaskAssigneeBrief[] {
  const selected = new Set(value.map((p) => p.employee_id))
  return [
    ...value,
    ...found
      .filter((m) => !selected.has(m.employee_id))
      .map((m) => ({
        employee_id: m.employee_id,
        email: m.email,
        full_name: m.full_name,
      })),
  ]
}

/** Подпись человека в списке: имя, а если его нет — почта. */
export function personLabel(p: TaskAssigneeBrief): string {
  return p.full_name || p.email || p.employee_id
}
