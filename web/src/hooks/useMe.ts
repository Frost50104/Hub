import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { api } from '@/lib/api'

export interface Me {
  employee_id: string
  email: string
  full_name: string
  tenant_id: string
  tenant_slug: string
  hub_role: 'admin' | 'member' | 'viewer' | null
}

export function useMe(): UseQueryResult<Me> {
  return useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<Me>('/me').then((r) => r.data),
    staleTime: 5 * 60_000,
  })
}
