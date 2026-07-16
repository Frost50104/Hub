import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import {
  learnApi,
  type AudienceDryRun,
  type AudienceRuleDraft,
  type AuditList,
  type EmployeeList,
  type EmployeeProfile,
  type OrgSnapshot,
  type UnlinkedLogin,
} from '@/lib/learn'

// ─── Оргструктура ────────────────────────────────────────────────────────────

export function useOrgSnapshot(): UseQueryResult<OrgSnapshot> {
  return useQuery({
    queryKey: ['learn-org'],
    queryFn: learnApi.orgSnapshot,
    staleTime: 60_000,
  })
}

/** Универсальная мутация оргструктуры: после успеха обновляем снапшот. */
export function useOrgMutation<TArgs, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
  opts?: { alsoInvalidate?: string[] },
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-org'] })
      for (const key of opts?.alsoInvalidate ?? []) {
        void qc.invalidateQueries({ queryKey: [key] })
      }
    },
  })
}

// ─── Сотрудники ──────────────────────────────────────────────────────────────

export interface EmployeeFilters {
  status?: 'active' | 'archived'
  q?: string
  store_id?: string
  position_id?: string
  offset?: number
}

export function useEmployees(filters: EmployeeFilters): UseQueryResult<EmployeeList> {
  return useQuery({
    queryKey: ['learn-employees', filters],
    queryFn: () => learnApi.employees({ ...filters, limit: 100 }),
    placeholderData: (prev) => prev,
  })
}

export function useEmployeeMutation<TArgs>(
  fn: (args: TArgs) => Promise<EmployeeProfile | void>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-employees'] })
      void qc.invalidateQueries({ queryKey: ['learn-unlinked'] })
    },
  })
}

export function useUnlinkedLogins(enabled: boolean): UseQueryResult<UnlinkedLogin[]> {
  return useQuery({
    queryKey: ['learn-unlinked'],
    queryFn: learnApi.unlinkedLogins,
    enabled,
  })
}

// ─── Audience dry-run ────────────────────────────────────────────────────────

export function useAudienceDryRun(
  body: { is_all: boolean; rules: AudienceRuleDraft[] } | null,
): UseQueryResult<AudienceDryRun> {
  return useQuery({
    queryKey: ['learn-audience-dry-run', body],
    queryFn: () => learnApi.audienceDryRun(body!),
    enabled: body !== null,
    placeholderData: (prev) => prev,
    meta: { suppressGlobalError: true },
  })
}

// ─── Аудит ───────────────────────────────────────────────────────────────────

export function useAuditLog(params: {
  object_type?: string
  offset?: number
}): UseQueryResult<AuditList> {
  return useQuery({
    queryKey: ['learn-audit', params],
    queryFn: () => learnApi.audit({ ...params, limit: 50 }),
    placeholderData: (prev) => prev,
  })
}
