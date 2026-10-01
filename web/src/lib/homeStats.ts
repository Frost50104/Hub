import type { MyStats, TrendPoint } from './stats'

/** Окна блока «Ваша статистика». Оба приезжают одним ответом. */
export type HomePeriod = 7 | 30

/** Точка графика «Главной»: два ряда на один день. */
export interface TrendDayPoint {
  key: string
  completed: number
  created: number
  /** «24 сентября» — подписи краёв и оси. */
  label: string
  /** «24 сентября, ср» — заголовок тултипа. */
  labelLong: string
}

export interface HomeStatsView {
  /** Числа за выбранный период. */
  completed: number
  created: number
  /** Состояние на сейчас — от периода не зависит. */
  overdue: number
  open: number
  /** Точки графика: хвост `daily` длиной в период. */
  points: TrendDayPoint[]
  startLabel: string
  endLabel: string
  /** Максимумы рядов за период — масштаб и подпись считает график по видимым. */
  max: { completed: number; created: number }
  /** За период ни закрыто, ни заведено ничего — вместо графика строка. */
  isEmpty: boolean
}

/**
 * Дата дня графика человеческим текстом.
 *
 * `T12:00:00`, а не полночь: браузер читает голую дату как UTC, и в минусовых
 * зонах «19 августа» превращалось бы в «18 августа». Тот же приём в
 * `ProjectDashboard.tsx`.
 */
export function fmtDay(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
  })
}

/** «24 сентября, ср» — для тултипа: день недели помогает узнать «тот самый». */
export function fmtDayWeekday(iso: string): string {
  const d = new Date(`${iso}T12:00:00`)
  const weekday = d.toLocaleDateString('ru-RU', { weekday: 'short' }).replace('.', '')
  return `${fmtDay(iso)}, ${weekday}`
}

/**
 * Срез ответа под выбранный период.
 *
 * Сеть при переключении не трогаем: `daily` всегда 30 точек, «7 дней» —
 * последние 7 из них. Хвост, а не голова: последняя точка — сегодня.
 * `created` у точки optional: кэш старого ответа и фикстуры стенда его не
 * несут — считаем нулём, а не ломаем график.
 */
export function homeStatsView(stats: MyStats, period: HomePeriod): HomeStatsView {
  const daily: TrendPoint[] = stats.daily.slice(-period)
  const maxCompleted = daily.reduce((m, p) => Math.max(m, p.count), 0)
  const maxCreated = daily.reduce((m, p) => Math.max(m, p.created ?? 0), 0)
  return {
    completed: period === 7 ? stats.completed_7 : stats.completed_30,
    created: period === 7 ? stats.created_7 : stats.created_30,
    overdue: stats.overdue_now,
    open: stats.open_now,
    points: daily.map((p) => ({
      key: p.day,
      completed: p.count,
      created: p.created ?? 0,
      label: fmtDay(p.day),
      labelLong: fmtDayWeekday(p.day),
    })),
    startLabel: daily.length > 0 ? fmtDay(daily[0]!.day) : '',
    endLabel: daily.length > 0 ? fmtDay(daily[daily.length - 1]!.day) : '',
    max: { completed: maxCompleted, created: maxCreated },
    // Раньше пустым считался период без ЗАКРЫТИЙ — с двумя рядами график
    // прятался бы при «создано > 0».
    isEmpty: maxCompleted === 0 && maxCreated === 0,
  }
}
