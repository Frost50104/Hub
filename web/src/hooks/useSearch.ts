import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { api } from '@/lib/api'

import { useDebouncedValue } from './useDebouncedValue'

export interface SearchHit {
  kind: 'project' | 'task'
  id: string
  title: string
  subtitle: string | null
  project_id?: string | null
}

export interface SearchResponse {
  projects: SearchHit[]
  tasks: SearchHit[]
}

export function useSearch(rawQuery: string): UseQueryResult<SearchResponse> {
  const debounced = useDebouncedValue(rawQuery.trim(), 200)
  return useQuery({
    queryKey: ['search', debounced],
    queryFn: () =>
      api
        .get<SearchResponse>('/search', { params: { q: debounced } })
        .then((r) => r.data),
    enabled: debounced.length >= 2,
  })
}
