import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { tenantApi, type TenantMember } from '@/lib/tenant'

import { useDebouncedValue } from './useDebouncedValue'

export function useTenantMembers(
  rawQuery: string,
): UseQueryResult<TenantMember[]> {
  const q = useDebouncedValue(rawQuery.trim().toLowerCase(), 150)
  return useQuery({
    queryKey: ['tenant-members', q],
    queryFn: () => tenantApi.members(q),
    staleTime: 30_000,
  })
}
