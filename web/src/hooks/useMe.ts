import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { useEffect } from 'react'

import { api } from '@/lib/api'
import { clearSentryUser, identifySentryUser } from '@/lib/sentry'

export interface MeProfile {
  id: string
  org_role: 'employee' | 'tu' | 'franchisee_owner' | 'office'
  content_role: 'none' | 'author' | 'publisher'
  status: 'active' | 'archived'
  position_id: string | null
  store_id: string | null
  status_text: string | null
}

export interface Me {
  employee_id: string
  email: string
  full_name: string
  tenant_id: string
  tenant_slug: string
  hub_role: 'admin' | 'member' | 'viewer' | null
  /** Learn-профиль (HR-карточка); null у юзеров без hub-роли. */
  profile: MeProfile | null
  /** Карточка с этим email в архиве — требуется восстановление админом. */
  profile_needs_restore: boolean
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
