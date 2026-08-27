import { api } from './api'

export interface TrendPoint {
  day: string // YYYY-MM-DD
  count: number
}

export interface WorkloadEntry {
  employee_id: string | null
  full_name: string | null
  email: string | null
  active_count: number
  done_count: number
  /** Просроченных у исполнителя. Optional: объект из кэша старого бандла поля не несёт. */
  overdue_count?: number
}

export interface NumberStats {
  sum: number | null
  avg: number | null
  min: number | null
  max: number | null
  count: number
}

export interface OptionCount {
  id: string
  label: string
  count: number
}

export interface CustomFieldStat {
  field_id: string
  name: string
  type: 'number' | 'select' | 'multi_select'
  number?: NumberStats | null
  select?: { options: OptionCount[] } | null
}

export interface ProjectStats {
  /** Состояние задач: `{done, open}` (0044 — вместо четырёх статусов). */
  done_breakdown: Record<'done' | 'open', number>
  /** Срез по колонкам доски: ключ — id колонки, «None» — без колонки. */
  stage_breakdown?: Record<string, number>
  priority_breakdown: Record<string, number>
  completed_trend: TrendPoint[]
  overdue_count: number
  workload: WorkloadEntry[]
  custom_field_stats: CustomFieldStat[]
  total_active: number
  total_archived: number
}

/**
 * Личные цифры для блока «Ваша статистика» на «Главной».
 *
 * Оба окна приезжают одним ответом: переключатель «7 / 30 дней» не должен
 * ходить в сеть. `daily` — всегда 30 точек (последняя — сегодня), вид «7 дней»
 * это её хвост (`lib/homeStats.ts`).
 */
export interface MyStats {
  completed_7: number
  completed_30: number
  created_7: number
  created_30: number
  /** Состояние на сейчас — от выбранного периода НЕ зависит. */
  overdue_now: number
  open_now: number
  daily: TrendPoint[]
}

export const statsApi = {
  forProject: (projectId: string): Promise<ProjectStats> =>
    api.get<ProjectStats>(`/projects/${projectId}/stats`).then((r) => r.data),
  forMe: (): Promise<MyStats> => api.get<MyStats>('/me/stats').then((r) => r.data),
}
