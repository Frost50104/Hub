import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { tenantApi, type TenantMember } from '@/lib/tenant'

import { useDebouncedValue } from './useDebouncedValue'

export function useTenantMembers(
  rawQuery: string,
  /** Мультивыбору дефолтных 10 мало: список там — рабочая поверхность. */
  limit = 10,
): UseQueryResult<TenantMember[]> {
  const q = useDebouncedValue(rawQuery.trim().toLowerCase(), 150)
  return useQuery({
    queryKey: ['tenant-members', q, limit],
    queryFn: () => tenantApi.members(q, limit),
    staleTime: 30_000,
  })
}
