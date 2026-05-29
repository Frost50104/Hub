import { api } from './api'

export interface SearchHit {
  kind: 'project' | 'task'
  id: string
  title: string
  subtitle: string | null
  project_id?: string | null
}

export interface SearchResponseLegacy {
  projects: SearchHit[]
  tasks: SearchHit[]
}

export interface SearchTaskHit {
  id: string
  title: string
  status: 'todo' | 'in_progress' | 'in_review' | 'done'
  priority: 'low' | 'medium' | 'high' | 'urgent'
  due_at: string | null
  assignee_id: string | null
}

export interface SearchGroup {
  project_id: string
  project_name: string
  project_key: string
  tasks: SearchTaskHit[]
}

export interface ParsedDsl {
  text: string
  assignee: string | null
  status: string | null
  priority: string | null
  due_op: '<' | '>' | '=' | null
  due_date: string | null
  created_op: '<' | '>' | '=' | null
  created_date: string | null
}

export interface SearchResponseGrouped {
  groups: SearchGroup[]
  total: number
  parsed: ParsedDsl
}

export const searchApi = {
  quick: (q: string): Promise<SearchResponseLegacy> =>
    api.get<SearchResponseLegacy>('/search', { params: { q } }).then((r) => r.data),
  grouped: (q: string): Promise<SearchResponseGrouped> =>
    api
      .get<SearchResponseGrouped>('/search', { params: { q, group_by: 'project' } })
      .then((r) => r.data),
}
