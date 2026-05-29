import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import {
  searchApi,
  type SearchResponseGrouped,
  type SearchResponseLegacy,
} from '@/lib/search'

import { useDebouncedValue } from './useDebouncedValue'

// Re-export for back-compat with existing imports.
export type { SearchHit, SearchResponseLegacy as SearchResponse } from '@/lib/search'

export function useSearch(
  rawQuery: string,
): UseQueryResult<SearchResponseLegacy> {
  const debounced = useDebouncedValue(rawQuery.trim(), 200)
  return useQuery({
    queryKey: ['search', 'quick', debounced],
    queryFn: () => searchApi.quick(debounced),
    enabled: debounced.length >= 2,
  })
}

export function useAdvancedSearch(
  rawQuery: string,
): UseQueryResult<SearchResponseGrouped> {
  const debounced = useDebouncedValue(rawQuery.trim(), 300)
  return useQuery({
    queryKey: ['search', 'grouped', debounced],
    queryFn: () => searchApi.grouped(debounced),
    enabled: debounced.length >= 2,
  })
}
