import { api } from './api'

// ─── Оргструктура ────────────────────────────────────────────────────────────

export interface OrgRef {
  id: string
  name: string
  description: string | null
  archived_at: string | null
}

export interface OrgStore {
  id: string
  name: string
  code: string | null
  address: string | null
  franchisee_id: string | null
  archived_at: string | null
}

export interface OrgDepartment {
  id: string
  name: string
  parent_id: string | null
}

export interface OrgGroup {
  id: string
  name: string
  description: string | null
  member_ids: string[]
}

export interface OrgSnapshot {
  positions: OrgRef[]
  position_groups: OrgGroup[]
  stores: OrgStore[]
  store_groups: OrgGroup[]
  franchisees: OrgRef[]
  franchisee_groups: OrgGroup[]
  departments: OrgDepartment[]
  user_groups: OrgGroup[]
}

export type GroupKind =
  | 'position-groups'
  | 'store-groups'
  | 'franchisee-groups'
  | 'user-groups'

// ─── Сотрудники ──────────────────────────────────────────────────────────────

export type OrgRole = 'employee' | 'tu' | 'franchisee_owner' | 'office'
export type ContentRole = 'none' | 'author' | 'publisher'

export const ORG_ROLE_LABEL: Record<OrgRole, string> = {
  employee: 'Сотрудник',
  tu: 'Территориальный управляющий',
  franchisee_owner: 'Франчайзи',
  office: 'Офис',
}

export const CONTENT_ROLE_LABEL: Record<ContentRole, string> = {
  none: '—',
  author: 'Автор контента',
  publisher: 'Публикатор',
}

export interface EmployeeProfile {
  id: string
  employee_id: string | null
  email: string
  full_name: string
  phone: string | null
  position_id: string | null
  store_id: string | null
  department_id: string | null
  franchisee_id: string | null
  manager_profile_id: string | null
  org_role: OrgRole
  content_role: ContentRole
  hired_at: string | null
  status_text: string | null
  status: 'active' | 'archived'
  archived_at: string | null
  archive_reason: string | null
  last_activity_at: string | null
  created_at: string
  /** Закреплённые магазины (только для org_role=tu). */
  tu_store_ids: string[]
}

export interface EmployeeList {
  items: EmployeeProfile[]
  total: number
}

export interface EmployeeUpsert {
  email?: string
  full_name?: string
  phone?: string | null
  position_id?: string | null
  store_id?: string | null
  department_id?: string | null
  franchisee_id?: string | null
  manager_profile_id?: string | null
  org_role?: OrgRole
  content_role?: ContentRole
  hired_at?: string | null
}

export interface UnlinkedLogin {
  employee_id: string
  email: string
  full_name: string
  last_seen_at: string
}

export interface ImportReport {
  created: number
  skipped: number
  errors: string[]
  dry_run: boolean
}

// ─── Audience ────────────────────────────────────────────────────────────────

export interface AudienceRuleDraft {
  mode: 'include' | 'exclude'
  profile_ids: string[]
  position_ids: string[]
  position_group_ids: string[]
  store_ids: string[]
  store_group_ids: string[]
  franchisee_ids: string[]
  franchisee_group_ids: string[]
  department_ids: string[]
  user_group_ids: string[]
}

export function emptyRule(mode: 'include' | 'exclude'): AudienceRuleDraft {
  return {
    mode,
    profile_ids: [],
    position_ids: [],
    position_group_ids: [],
    store_ids: [],
    store_group_ids: [],
    franchisee_ids: [],
    franchisee_group_ids: [],
    department_ids: [],
    user_group_ids: [],
  }
}

export interface AudienceDryRun {
  count: number
  sample: { id: string; full_name: string }[]
}

// ─── Аудит ───────────────────────────────────────────────────────────────────

export interface AuditEntry {
  id: number
  actor_id: string | null
  actor_name: string | null
  action: string
  object_type: string
  object_id: string | null
  object_label: string | null
  diff: Record<string, { old: unknown; new: unknown }> | null
  created_at: string
}

export interface AuditList {
  items: AuditEntry[]
  total: number
}

// ─── API ─────────────────────────────────────────────────────────────────────

export const learnApi = {
  orgSnapshot: (): Promise<OrgSnapshot> =>
    api.get<OrgSnapshot>('/learn/org').then((r) => r.data),

  createRef: (
    kind: 'positions' | 'franchisees',
    body: { name: string; description?: string },
  ): Promise<OrgRef> => api.post<OrgRef>(`/learn/org/${kind}`, body).then((r) => r.data),
  updateRef: (
    kind: 'positions' | 'franchisees',
    id: string,
    body: { name?: string; description?: string; archived?: boolean },
  ): Promise<OrgRef> =>
    api.patch<OrgRef>(`/learn/org/${kind}/${id}`, body).then((r) => r.data),
  deleteRef: (kind: 'positions' | 'franchisees', id: string): Promise<void> =>
    api.delete(`/learn/org/${kind}/${id}`).then(() => undefined),

  createStore: (body: {
    name: string
    code?: string
    address?: string
    franchisee_id?: string | null
  }): Promise<OrgStore> => api.post<OrgStore>('/learn/org/stores', body).then((r) => r.data),
  updateStore: (
    id: string,
    body: Partial<{
      name: string
      code: string | null
      address: string | null
      franchisee_id: string | null
      archived: boolean
    }>,
  ): Promise<OrgStore> =>
    api.patch<OrgStore>(`/learn/org/stores/${id}`, body).then((r) => r.data),
  deleteStore: (id: string): Promise<void> =>
    api.delete(`/learn/org/stores/${id}`).then(() => undefined),

  createDepartment: (body: { name: string; parent_id?: string | null }): Promise<OrgDepartment> =>
    api.post<OrgDepartment>('/learn/org/departments', body).then((r) => r.data),
  updateDepartment: (
    id: string,
    body: Partial<{ name: string; parent_id: string | null }>,
  ): Promise<OrgDepartment> =>
    api.patch<OrgDepartment>(`/learn/org/departments/${id}`, body).then((r) => r.data),
  deleteDepartment: (id: string): Promise<void> =>
    api.delete(`/learn/org/departments/${id}`).then(() => undefined),

  createGroup: (kind: GroupKind, body: { name: string; description?: string }): Promise<OrgGroup> =>
    api.post<OrgGroup>(`/learn/org/${kind}`, body).then((r) => r.data),
  renameGroup: (
    kind: GroupKind,
    id: string,
    body: { name?: string; description?: string },
  ): Promise<OrgGroup> =>
    api.patch<OrgGroup>(`/learn/org/${kind}/${id}`, body).then((r) => r.data),
  replaceGroupMembers: (kind: GroupKind, id: string, memberIds: string[]): Promise<OrgGroup> =>
    api
      .put<OrgGroup>(`/learn/org/${kind}/${id}/members`, { member_ids: memberIds })
      .then((r) => r.data),
  deleteGroup: (kind: GroupKind, id: string): Promise<void> =>
    api.delete(`/learn/org/${kind}/${id}`).then(() => undefined),

  employees: (params: {
    status?: 'active' | 'archived'
    q?: string
    store_id?: string
    position_id?: string
    limit?: number
    offset?: number
  }): Promise<EmployeeList> =>
    api.get<EmployeeList>('/learn/employees', { params }).then((r) => r.data),
  employee: (id: string): Promise<EmployeeProfile> =>
    api.get<EmployeeProfile>(`/learn/employees/${id}`).then((r) => r.data),
  createEmployee: (body: EmployeeUpsert & { email: string; full_name: string }): Promise<EmployeeProfile> =>
    api.post<EmployeeProfile>('/learn/employees', body).then((r) => r.data),
  updateEmployee: (id: string, body: EmployeeUpsert & { status_text?: string | null }): Promise<EmployeeProfile> =>
    api.patch<EmployeeProfile>(`/learn/employees/${id}`, body).then((r) => r.data),
  replaceTuStores: (id: string, storeIds: string[]): Promise<EmployeeProfile> =>
    api
      .put<EmployeeProfile>(`/learn/employees/${id}/tu-stores`, { store_ids: storeIds })
      .then((r) => r.data),
  archiveEmployee: (id: string): Promise<EmployeeProfile> =>
    api
      .post<EmployeeProfile>(`/learn/employees/${id}/archive`, { reason: 'manual' })
      .then((r) => r.data),
  restoreEmployee: (id: string, employeeId?: string): Promise<EmployeeProfile> =>
    api
      .post<EmployeeProfile>(`/learn/employees/${id}/restore`, {
        employee_id: employeeId ?? null,
      })
      .then((r) => r.data),
  linkEmployee: (id: string, employeeId: string): Promise<EmployeeProfile> =>
    api
      .post<EmployeeProfile>(`/learn/employees/${id}/link`, { employee_id: employeeId })
      .then((r) => r.data),
  unlinkedLogins: (): Promise<UnlinkedLogin[]> =>
    api.get<UnlinkedLogin[]>('/learn/employees/unlinked').then((r) => r.data),
  importEmployees: (file: File, opts: { dryRun: boolean }): Promise<ImportReport> => {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<ImportReport>('/learn/employees/import', form, {
        params: { dry_run: opts.dryRun },
      })
      .then((r) => r.data)
  },

  audienceDryRun: (body: {
    is_all: boolean
    rules: AudienceRuleDraft[]
  }): Promise<AudienceDryRun> =>
    api.post<AudienceDryRun>('/learn/audiences/dry-run', body).then((r) => r.data),
  audienceRebuild: (): Promise<{ audiences_changed: number }> =>
    api.post<{ audiences_changed: number }>('/learn/audiences/rebuild').then((r) => r.data),

  audit: (params: {
    object_type?: string
    limit?: number
    offset?: number
  }): Promise<AuditList> => api.get<AuditList>('/learn/audit', { params }).then((r) => r.data),
}
