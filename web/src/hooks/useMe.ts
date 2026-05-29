import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { useEffect } from 'react'

import { api } from '@/lib/api'
import { clearSentryUser, identifySentryUser } from '@/lib/sentry'

export interface Me {
  employee_id: string
  email: string
  full_name: string
  tenant_id: string
  tenant_slug: string
  hub_role: 'admin' | 'member' | 'viewer' | null
}

export function useMe(): UseQueryResult<Me> {
  const query = useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<Me>('/me').then((r) => r.data),
    staleTime: 5 * 60_000,
  })

  useEffect(() => {
    if (query.data) {
      identifySentryUser({
        id: query.data.employee_id,
        email: query.data.email,
        username: query.data.full_name,
      })
    } else if (query.isError) {
      clearSentryUser()
    }
  }, [query.data, query.isError])

  return query
}
