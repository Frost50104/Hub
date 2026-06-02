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
  status_breakdown: Record<string, number>
  priority_breakdown: Record<string, number>
  completed_trend: TrendPoint[]
  overdue_count: number
  workload: WorkloadEntry[]
  custom_field_stats: CustomFieldStat[]
  total_active: number
  total_archived: number
}

export const statsApi = {
  forProject: (projectId: string): Promise<ProjectStats> =>
    api.get<ProjectStats>(`/projects/${projectId}/stats`).then((r) => r.data),
}
