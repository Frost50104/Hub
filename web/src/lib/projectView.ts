/**
 * Вид страницы проекта: вкладки и правило «что открыть, если в адресе вида нет».
 *
 * Отдельным чистым модулем — правило дефолта тестируется без компонента, а
 * список вкладок нужен и странице, и этому правилу.
 *
 * Дефолт — ДОСКА, если у проекта есть хотя бы одна колонка, иначе СПИСОК
 * (просьба пользователей 01.10; раньше — всегда список). Почему не «всегда
 * доска»: задачи без колонки на доску не попадают (0046), а с 26.08 новые
 * проекты рождаются без колонок — у такого проекта доска открывалась бы
 * пустой при живых задачах (в коде `BoardView` назван «Подбор» с 1 277
 * задачами без колонок). Решение владельца: без колонок — список, на телефоне
 * то же правило, выбор не запоминается.
 */

export const PROJECT_VIEWS = [
  { key: 'list', label: 'Список' },
  { key: 'board', label: 'Доска' },
  { key: 'calendar', label: 'Календарь' },
  { key: 'timeline', label: 'Хронология' },
  { key: 'dashboard', label: 'Дашборд' },
  { key: 'members', label: 'Участники' },
  { key: 'about', label: 'О проекте' },
] as const

export type ProjectView = (typeof PROJECT_VIEWS)[number]['key']

export function isProjectView(raw: string | null | undefined): raw is ProjectView {
  return PROJECT_VIEWS.some((v) => v.key === raw)
}

export interface ResolveProjectViewInput {
  /** `?view=` из адреса; `null` — параметра нет. */
  requested: string | null
  /** Число колонок проекта; `undefined` — ещё грузятся. */
  stageCount: number | undefined
  /** Запрос колонок упал: дефолт решаем без них, страницу не держим. */
  stagesFailed: boolean
  /** Дашборд доступен (у шаблона его нет — `templatePageGate`). */
  showDashboard: boolean
}

/**
 * Явный валидный вид побеждает при любом состоянии колонок — ссылка на доску
 * обязана открыть доску, а «Список», выбранный человеком, не должен ждать
 * запроса. `?view=dashboard` у шаблона считается «не запрошено» и уходит в
 * дефолт. Без вида: колонки ещё не известны → `null` («рисуй скелет» —
 * список не должен мелькнуть перед доской).
 *
 * Вызывающий применяет результат ОДИН раз — канонизирует голый адрес в
 * `?view=…`; иначе удаление последней колонки переключало бы вкладку под
 * ногами, а «Колонок нет» на доске стало бы недостижимым с голого адреса.
 */
export function resolveProjectView(input: ResolveProjectViewInput): ProjectView | null {
  const { requested, stageCount, stagesFailed, showDashboard } = input
  if (isProjectView(requested) && (requested !== 'dashboard' || showDashboard)) {
    return requested
  }
  if (stagesFailed) return 'list'
  if (stageCount === undefined) return null
  return stageCount > 0 ? 'board' : 'list'
}
