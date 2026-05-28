import { api } from './api'

export interface TenantMember {
  employee_id: string
  email: string
  full_name: string
  /** Lower-cased local-part of email — used in `@handle` mentions. */
  handle: string
}

export const tenantApi = {
  members: (q?: string, limit = 10): Promise<TenantMember[]> =>
    api
      .get<TenantMember[]>('/tenant/members', { params: { q: q || undefined, limit } })
      .then((r) => r.data),
}
