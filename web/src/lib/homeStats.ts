import type { MyStats, TrendPoint } from './stats'
import { plural } from './typography'

/** Окна блока «Ваша статистика». Оба приезжают одним ответом. */
export type HomePeriod = 7 | 30

export interface HomeStatsView {
  /** Числа за выбранный период. */
  completed: number
  created: number
  /** Состояние на сейчас — от периода не зависит. */
  overdue: number
  open: number
  /** Точки графика: хвост `daily` длиной в период. */
  points: { key: string; value: number; title: string }[]
  startLabel: string
  endLabel: string
  maxLabel: string
  /** За период не закрыто ничего — вместо графика показываем строку. */
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

/**
 * Срез ответа под выбранный период.
 *
 * Сеть при переключении не трогаем: `daily` всегда 30 точек, «7 дней» —
 * последние 7 из них. Хвост, а не голова: последняя точка — сегодня.
 */
export function homeStatsView(stats: MyStats, period: HomePeriod): HomeStatsView {
  const daily: TrendPoint[] = stats.daily.slice(-period)
  const max = daily.reduce((m, p) => Math.max(m, p.count), 0)
  const completed = period === 7 ? stats.completed_7 : stats.completed_30
  return {
    completed,
    created: period === 7 ? stats.created_7 : stats.created_30,
    overdue: stats.overdue_now,
    open: stats.open_now,
    points: daily.map((p) => ({
      key: p.day,
      // Значение обязано быть доступно текстом: на телефоне нет hover, а тап
      // по столбику шириной в несколько пикселей невозможен.
      title: `${fmtDay(p.day)} — ${plural(p.count, 'закрыта', 'закрыто', 'закрыто')}`,
      value: p.count,
    })),
    startLabel: daily.length > 0 ? fmtDay(daily[0]!.day) : '',
    endLabel: daily.length > 0 ? fmtDay(daily[daily.length - 1]!.day) : '',
    maxLabel: `Максимум за день — ${max}`,
    isEmpty: max === 0,
  }
}
