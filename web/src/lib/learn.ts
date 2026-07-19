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

/** Бейдж продукт-роли у логотипа в сайдбаре (стиль Sonar). */
export const HUB_ROLE_BADGE: Record<'admin' | 'member' | 'viewer', string> = {
  admin: 'АДМИН',
  member: 'УЧАСТНИК',
  viewer: 'ПРОСМОТР',
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

// ─── Библиотека (Ф1) ─────────────────────────────────────────────────────────

export type ContentStatus = 'draft' | 'review' | 'published' | 'archived'

export const CONTENT_STATUS_LABEL: Record<ContentStatus, string> = {
  draft: 'Черновик',
  review: 'На согласовании',
  published: 'Опубликован',
  archived: 'Архив',
}

export interface LibrarySection {
  id: string
  parent_id: string | null
  title: string
  position: number
  audience_id: string | null
}

export interface MaterialVersion {
  version_no: number
  file_name: string
  mime: string
  size_bytes: number
  note: string | null
  created_at: string
}

export interface LibraryMaterial {
  id: string
  section_id: string | null
  audience_id: string | null
  title: string
  description: string | null
  kind: 'file' | 'link'
  url: string | null
  current_version_no: number | null
  requires_acknowledgement: boolean
  re_ack_on_new_version: boolean
  ack_deadline_days: number | null
  status: ContentStatus
  owner_id: string | null
  owner_name: string | null
  published_at: string | null
  review_period_months: number | null
  next_review_at: string | null
  updated_at: string
  current_version: MaterialVersion | null
  opened_by_me: boolean
  acked_by_me: boolean
  ack_pending: boolean
}

export interface LibraryData {
  sections: LibrarySection[]
  materials: LibraryMaterial[]
  content_role: 'admin' | 'publisher' | 'author' | 'none'
}

export interface MaterialUpsert {
  title?: string
  description?: string | null
  url?: string | null
  section_id?: string | null
  requires_acknowledgement?: boolean
  re_ack_on_new_version?: boolean
  ack_deadline_days?: number | null
  review_period_months?: number | null
}

export interface AckReportRow {
  profile_id: string
  full_name: string
  store_id: string | null
  granted_at: string | null
  opened_at: string | null
  acknowledged_at: string | null
  deadline_at: string | null
  overdue: boolean
}

export interface AckReport {
  material_id: string
  total: number
  acked: number
  rows: AckReportRow[]
}

// ─── Новости (Ф2) ────────────────────────────────────────────────────────────

// Единый тип rich-контента — структура описана в рендерере.
export type { RichDoc } from '@/components/learn/rich/RichRenderer'
import { type RichDoc } from '@/components/learn/rich/RichRenderer'

export const REACTION_EMOJIS = ['👍', '❤️', '🎉', '👏', '😄'] as const

export interface NewsPost {
  id: string
  audience_id: string | null
  title: string
  body: RichDoc
  allow_comments: boolean
  allow_reactions: boolean
  requires_acknowledgement: boolean
  pinned_until: string | null
  status: ContentStatus
  published_at: string | null
  created_at: string
  updated_at: string
  author_name: string | null
  reactions: Record<string, number>
  my_reactions: string[]
  comments_count: number
  acked_by_me: boolean
  ack_pending: boolean
  is_favorite: boolean
}

export interface NewsList {
  items: NewsPost[]
  total: number
  content_role: 'admin' | 'publisher' | 'author' | 'none'
}

export interface NewsComment {
  id: string
  author_id: string
  author_name: string | null
  body: string
  edited_at: string | null
  deleted_at: string | null
  created_at: string
}

// ─── Опросы (Ф2) ─────────────────────────────────────────────────────────────

export type QuestionType = 'single' | 'multi' | 'open' | 'scale' | 'enps'

export const QUESTION_TYPE_LABEL: Record<QuestionType, string> = {
  single: 'Один вариант',
  multi: 'Несколько вариантов',
  open: 'Открытый ответ',
  scale: 'Шкала',
  enps: 'eNPS (0–10)',
}

export interface SurveyQuestion {
  id: string
  qtype: QuestionType
  prompt: string
  options: { options?: string[]; min?: number; max?: number } | null
  required: boolean
  position: number
}

export interface Survey {
  id: string
  audience_id: string | null
  title: string
  description: string | null
  kind: 'standard' | 'enps' | 'pulse'
  is_anonymous: boolean
  opens_at: string | null
  closes_at: string | null
  status: ContentStatus
  published_at: string | null
  created_at: string
  questions: SurveyQuestion[]
  participated: boolean
  is_open_now: boolean
  participants: number
}

export interface SurveyListData {
  items: Survey[]
  content_role: 'admin' | 'publisher' | 'author' | 'none'
}

export interface QuestionDraft {
  qtype: QuestionType
  prompt: string
  options: { options?: string[]; min?: number; max?: number } | null
  required: boolean
}

export type AnswerValue =
  | { option: number }
  | { options: number[] }
  | { text: string }
  | { value: number }

export interface QuestionStats {
  question_id: string
  qtype: QuestionType
  prompt: string
  total_answers: number
  distribution: Record<string, number>
  texts: string[]
  enps_score: number | null
  groups: Record<
    string,
    'suppressed' | { total: number; distribution: Record<string, number>; enps_score?: number }
  >
}

export interface SurveyResults {
  survey_id: string
  participants: number
  audience_size: number
  dimension: string | null
  questions: QuestionStats[]
}

export interface FavoriteItem {
  object_type: string
  object_id: string
  title: string
  url_path: string
  created_at: string | null
}

// ─── Курсы (Ф3a) ─────────────────────────────────────────────────────────────

export type CourseType = 'mandatory' | 'recommended' | 'career' | 'info'
export type ProgressionMode = 'sequential' | 'free' | 'mixed'
export type LessonUnlockRule = 'inherit' | 'free' | 'after_prev_test'
export type LessonContentFormat = 'blocks' | 'pdf'

export const COURSE_TYPE_LABEL: Record<CourseType, string> = {
  mandatory: 'Обязательный',
  recommended: 'Рекомендованный',
  career: 'Карьерный',
  info: 'Информационный',
}

export const PROGRESSION_MODE_LABEL: Record<ProgressionMode, string> = {
  sequential: 'Последовательный',
  free: 'Свободный',
  mixed: 'Смешанный',
}

export interface LessonMeta {
  id: string
  title: string
  position: number
  content_format: LessonContentFormat
  unlock_rule: LessonUnlockRule
  status: 'draft' | 'published'
  locked: boolean
  completed: boolean
  started: boolean
}

export interface Course {
  id: string
  audience_id: string | null
  title: string
  description: string | null
  course_type: CourseType
  progression_mode: ProgressionMode
  certificate_enabled: boolean
  status: ContentStatus
  published_at: string | null
  created_at: string
  updated_at: string
  lessons_total: number
  lessons_completed: number
  enrolled: boolean
  due_at: string | null
  completed: boolean
}

export interface CourseList {
  items: Course[]
  content_role: string
}

export interface CourseDetail extends Course {
  lessons: LessonMeta[]
}

export interface LessonBlockState {
  answers?: Record<string, { answer: number; correct: boolean }>
  video?: Record<string, { intervals: [number, number][]; duration: number }>
}

export interface LessonContent {
  id: string
  course_id: string
  title: string
  position: number
  content_format: LessonContentFormat
  content: RichDoc | null
  pdf_url: string | null
  forbid_download: boolean
  unlock_rule: LessonUnlockRule
  status: 'draft' | 'published'
  completed: boolean
  block_state: LessonBlockState
  gate_blocks: string[]
  required_videos: string[]
  prev_lesson_id: string | null
  next_lesson_id: string | null
  next_locked: boolean
}

export interface LessonTemplate {
  id: string
  title: string
  content: RichDoc
  created_at: string
}

// ─── Тесты + рейтинг + сертификаты (Ф3b) ─────────────────────────────────────

export type QuizQuestionType = 'single' | 'multi' | 'open' | 'match' | 'order'

export const QUIZ_QUESTION_TYPE_LABEL: Record<QuizQuestionType, string> = {
  single: 'Один из списка',
  multi: 'Несколько из списка',
  open: 'Открытый ответ',
  match: 'Сопоставление',
  order: 'Порядок',
}

export interface QuizQuestionDraft {
  qtype: QuizQuestionType
  prompt: string
  media_id?: string | null
  options: Record<string, unknown>
  answer?: Record<string, unknown> | null
  points: number
}

export interface QuizQuestionFull extends QuizQuestionDraft {
  id: string
  position: number
  media_url?: string | null
}

export interface QuizSettings {
  title: string
  description?: string | null
  status: 'draft' | 'published'
  pass_score_pct: number
  attempts_limit: number | null
  shuffle_questions: boolean
  shuffle_options: boolean
  show_correct_answers: boolean
  is_required: boolean
}

export interface QuizManage extends QuizSettings {
  id: string
  course_id: string
  lesson_id: string | null
  questions: QuizQuestionFull[]
}

export interface QuizConsumer {
  id: string
  lesson_id: string | null
  title: string
  description: string | null
  pass_score_pct: number
  attempts_limit: number | null
  is_required: boolean
  show_correct_answers: boolean
  question_count: number
  attempts_used: number
  best_score_pct: number | null
  passed: boolean
  pending_review: boolean
  active_attempt_id: string | null
  can_start: boolean
}

export interface QuizSnapshotQuestion {
  id: string
  qtype: QuizQuestionType
  prompt: string
  media_id: string | null
  media_url: string | null
  options: {
    options?: string[]
    left?: string[]
    right?: string[]
    items?: string[]
  }
  points: number
}

export interface QuizAttempt {
  id: string
  quiz_id: string
  attempt_no: number
  questions: QuizSnapshotQuestion[]
  answers: Record<string, unknown>
  started_at: string
  finished_at: string | null
  score_pct: number | null
  passed: boolean | null
  needs_review: boolean
  results: Record<string, boolean | null> | null
  correct_answers: Record<string, Record<string, unknown>> | null
}

export interface ReviewQueueItem {
  attempt_id: string
  quiz_id: string
  quiz_title: string
  course_id: string
  profile_id: string
  employee_name: string
  finished_at: string | null
  open_question_count: number
}

export interface RatingRow {
  profile_id: string
  full_name: string
  position_name: string | null
  store_name: string | null
  points: number
  rank: number
  is_me: boolean
}

export interface RatingData {
  period: 'month' | 'quarter'
  scope: 'all' | 'store'
  rows: RatingRow[]
  me: RatingRow | null
  total_participants: number
}

export interface CertificateInfo {
  id: string
  serial: string
  course_id: string
  course_title: string
  full_name: string
  issued_at: string
}

// ─── Ассортимент + витрина + профиль (Ф4) ────────────────────────────────────

export interface ProductCategory {
  id: string
  title: string
  position: number
}

export interface ProductLink {
  object_type: 'course' | 'lesson' | 'material'
  object_id: string
  title: string | null
  url_path: string | null
}

export interface ProductCard {
  id: string
  category_id: string | null
  audience_id: string | null
  title: string
  description: string | null
  composition: string | null
  allergens: string | null
  shelf_life: string | null
  serving: string | null
  upsell: string | null
  status: ContentStatus
  published_at: string | null
  updated_at: string
  photo_urls: string[]
  links: ProductLink[]
  viewed_by_me: boolean
}

export interface ProductListData {
  categories: ProductCategory[]
  items: ProductCard[]
  content_role: string
}

export interface ProductUpsert {
  title?: string
  description?: string | null
  category_id?: string | null
  photos?: { media_id: string }[]
  composition?: string | null
  allergens?: string | null
  shelf_life?: string | null
  serving?: string | null
  upsell?: string | null
  links?: { object_type: 'course' | 'lesson' | 'material'; object_id: string }[]
}

export interface HomeCourse {
  id: string
  title: string
  course_type: CourseType
  lessons_total: number
  lessons_completed: number
  due_at: string | null
}

export interface HomeData {
  courses: HomeCourse[]
  pending_acks: { id: string; title: string; deadline_at: string | null }[]
  novelties: {
    object_type: string
    object_id: string
    title: string
    url_path: string
    published_at: string | null
  }[]
  surveys: { id: string; title: string; kind: string; closes_at: string | null }[]
  rating: { points: number; rank: number | null; total_participants: number } | null
}

export interface LearnProfile {
  profile_id: string | null
  full_name: string
  email: string
  avatar_url: string | null
  position_name: string | null
  store_name: string | null
  department_name: string | null
  org_role: OrgRole | null
  content_role: string | null
  status_text: string | null
  hired_at: string | null
  tenure_days: number | null
}

// ─── Поиск + аналитика + автосценарии (Ф5) ───────────────────────────────────

export interface LearnSearchHit {
  object_type: string
  object_id: string
  title: string
  snippet: string | null
  url_path: string
  type_label: string
}

export interface LearnSearchData {
  query: string
  total: number
  hits: LearnSearchHit[]
}

export interface AnalyticsData {
  scope: string
  overview: {
    employees_total: number
    employees_linked: number
    engaged_30d: number
    points_30d: number
  }
  courses: {
    id: string
    title: string
    course_type: CourseType
    enrolled: number
    completed: number
    avg_quiz_score: number | null
  }[]
  fail_questions: {
    prompt: string
    quiz_title: string
    attempts: number
    fail_rate_pct: number
  }[]
  acks: { id: string; title: string; acked: number; total: number }[]
}

export type AutomationTrigger = 'profile_activated' | 'position_assigned'

export const AUTOMATION_TRIGGER_LABEL: Record<AutomationTrigger, string> = {
  profile_activated: 'Сотрудник активирован (первый вход)',
  position_assigned: 'Назначена должность',
}

export interface AutomationRule {
  id: string
  title: string
  trigger: AutomationTrigger
  position_ids: string[]
  course_id: string
  course_title: string | null
  due_days: number | null
  enabled: boolean
  applies_from: string
  jobs_pending: number
  jobs_done: number
}

export interface AutomationRuleUpsert {
  title: string
  trigger: AutomationTrigger
  position_ids: string[]
  course_id: string
  due_days: number | null
  enabled: boolean
}

export interface AutomationJob {
  id: string
  profile_id: string
  employee_name: string | null
  status: 'pending' | 'done' | 'cancelled'
  due_at: string | null
  created_at: string
  executed_at: string | null
}

// ─── AI-помощник (Ф6) ────────────────────────────────────────────────────────

export interface AiStatus {
  configured: boolean
  provider: string | null
}

export interface AiSource {
  title: string
  url_path: string
}

export interface AiAskResponse {
  conversation_id: string
  answer: string
  sources: AiSource[]
}

export interface AiConversation {
  id: string
  title: string
  updated_at: string
}

export interface AiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources: AiSource[] | null
  created_at: string
}

export type MediaKind = 'image' | 'video' | 'pdf'

export interface MediaUploadResult {
  id: string
  kind: MediaKind
  file_name: string
  mime: string
  size_bytes: number
  url: string
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

  // ─── Библиотека ────────────────────────────────────────────────────────────
  library: (manage: boolean): Promise<LibraryData> =>
    api
      .get<LibraryData>('/learn/library', { params: { manage: manage || undefined } })
      .then((r) => r.data),
  createSection: (body: { title: string; parent_id?: string | null }): Promise<LibrarySection> =>
    api.post<LibrarySection>('/learn/library/sections', body).then((r) => r.data),
  renameSection: (id: string, title: string): Promise<LibrarySection> =>
    api.patch<LibrarySection>(`/learn/library/sections/${id}`, { title }).then((r) => r.data),
  deleteSection: (id: string): Promise<void> =>
    api.delete(`/learn/library/sections/${id}`).then(() => undefined),

  createMaterial: (
    body: MaterialUpsert & { title: string; kind: 'file' | 'link' },
  ): Promise<LibraryMaterial> =>
    api.post<LibraryMaterial>('/learn/library/materials', body).then((r) => r.data),
  updateMaterial: (id: string, body: MaterialUpsert): Promise<LibraryMaterial> =>
    api.patch<LibraryMaterial>(`/learn/library/materials/${id}`, body).then((r) => r.data),
  deleteMaterial: (id: string): Promise<void> =>
    api.delete(`/learn/library/materials/${id}`).then(() => undefined),
  uploadVersion: (id: string, file: File): Promise<LibraryMaterial> => {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<LibraryMaterial>(`/learn/library/materials/${id}/versions`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },
  materialVersions: (id: string): Promise<MaterialVersion[]> =>
    api.get<MaterialVersion[]>(`/learn/library/materials/${id}/versions`).then((r) => r.data),
  setMaterialStatus: (id: string, status: ContentStatus): Promise<LibraryMaterial> =>
    api
      .post<LibraryMaterial>(`/learn/library/materials/${id}/status`, { status })
      .then((r) => r.data),
  setMaterialAudience: (
    id: string,
    body: { is_all: boolean; rules: AudienceRuleDraft[] },
  ): Promise<LibraryMaterial> =>
    api
      .put<LibraryMaterial>(`/learn/library/materials/${id}/audience`, body)
      .then((r) => r.data),
  trackOpen: (id: string): Promise<void> =>
    api.post(`/learn/library/materials/${id}/open`).then(() => undefined),
  acknowledge: (id: string, versionNo: number): Promise<LibraryMaterial> =>
    api
      .post<LibraryMaterial>(`/learn/library/materials/${id}/ack`, { version_no: versionNo })
      .then((r) => r.data),
  ackReport: (id: string): Promise<AckReport> =>
    api.get<AckReport>(`/learn/library/materials/${id}/ack-report`).then((r) => r.data),

  // ─── Новости ───────────────────────────────────────────────────────────────
  news: (manage: boolean, offset = 0): Promise<NewsList> =>
    api
      .get<NewsList>('/learn/news', {
        params: { manage: manage || undefined, offset, limit: 20 },
      })
      .then((r) => r.data),
  createNews: (body: {
    title: string
    body: RichDoc
    allow_comments: boolean
    allow_reactions: boolean
    requires_acknowledgement: boolean
  }): Promise<NewsPost> => api.post<NewsPost>('/learn/news', body).then((r) => r.data),
  updateNews: (
    id: string,
    body: Partial<{
      title: string
      body: RichDoc
      allow_comments: boolean
      allow_reactions: boolean
      requires_acknowledgement: boolean
    }>,
  ): Promise<NewsPost> => api.patch<NewsPost>(`/learn/news/${id}`, body).then((r) => r.data),
  deleteNews: (id: string): Promise<void> =>
    api.delete(`/learn/news/${id}`).then(() => undefined),
  setNewsStatus: (id: string, status: ContentStatus): Promise<NewsPost> =>
    api.post<NewsPost>(`/learn/news/${id}/status`, { status }).then((r) => r.data),
  setNewsAudience: (
    id: string,
    body: { is_all: boolean; rules: AudienceRuleDraft[] },
  ): Promise<NewsPost> =>
    api.put<NewsPost>(`/learn/news/${id}/audience`, body).then((r) => r.data),
  toggleReaction: (id: string, emoji: string): Promise<void> =>
    api.post(`/learn/news/${id}/reactions`, { emoji }).then(() => undefined),
  ackNews: (id: string): Promise<void> =>
    api.post(`/learn/news/${id}/ack`).then(() => undefined),
  newsComments: (id: string): Promise<NewsComment[]> =>
    api.get<NewsComment[]>(`/learn/news/${id}/comments`).then((r) => r.data),
  addNewsComment: (id: string, body: string): Promise<NewsComment> =>
    api.post<NewsComment>(`/learn/news/${id}/comments`, { body }).then((r) => r.data),
  deleteNewsComment: (postId: string, commentId: string): Promise<void> =>
    api.delete(`/learn/news/${postId}/comments/${commentId}`).then(() => undefined),

  // ─── Опросы ────────────────────────────────────────────────────────────────
  surveys: (manage: boolean): Promise<SurveyListData> =>
    api
      .get<SurveyListData>('/learn/surveys', { params: { manage: manage || undefined } })
      .then((r) => r.data),
  survey: (id: string): Promise<Survey> =>
    api.get<Survey>(`/learn/surveys/${id}`).then((r) => r.data),
  createSurvey: (body: {
    title: string
    description?: string | null
    kind: string
    is_anonymous: boolean
    opens_at?: string | null
    closes_at?: string | null
  }): Promise<Survey> => api.post<Survey>('/learn/surveys', body).then((r) => r.data),
  updateSurvey: (
    id: string,
    body: Partial<{
      title: string
      description: string | null
      kind: string
      is_anonymous: boolean
      opens_at: string | null
      closes_at: string | null
    }>,
  ): Promise<Survey> => api.patch<Survey>(`/learn/surveys/${id}`, body).then((r) => r.data),
  replaceQuestions: (id: string, questions: QuestionDraft[]): Promise<Survey> =>
    api.put<Survey>(`/learn/surveys/${id}/questions`, { questions }).then((r) => r.data),
  deleteSurvey: (id: string): Promise<void> =>
    api.delete(`/learn/surveys/${id}`).then(() => undefined),
  setSurveyStatus: (id: string, status: ContentStatus): Promise<Survey> =>
    api.post<Survey>(`/learn/surveys/${id}/status`, { status }).then((r) => r.data),
  setSurveyAudience: (
    id: string,
    body: { is_all: boolean; rules: AudienceRuleDraft[] },
  ): Promise<Survey> =>
    api.put<Survey>(`/learn/surveys/${id}/audience`, body).then((r) => r.data),
  submitSurvey: (
    id: string,
    answers: { question_id: string; value: AnswerValue }[],
  ): Promise<Survey> =>
    api.post<Survey>(`/learn/surveys/${id}/submit`, { answers }).then((r) => r.data),
  surveyResults: (id: string, dimension?: string): Promise<SurveyResults> =>
    api
      .get<SurveyResults>(`/learn/surveys/${id}/results`, {
        params: { dimension: dimension || undefined },
      })
      .then((r) => r.data),

  // ─── Избранное / недавнее ──────────────────────────────────────────────────
  toggleFavorite: (objectType: string, objectId: string): Promise<{ is_favorite: boolean }> =>
    api
      .post<{ is_favorite: boolean }>('/learn/favorites/toggle', {
        object_type: objectType,
        object_id: objectId,
      })
      .then((r) => r.data),
  favorites: (): Promise<FavoriteItem[]> =>
    api.get<FavoriteItem[]>('/learn/favorites').then((r) => r.data),
  recent: (): Promise<FavoriteItem[]> =>
    api.get<FavoriteItem[]>('/learn/recent').then((r) => r.data),

  // ─── Курсы (Ф3a) ───────────────────────────────────────────────────────────
  courses: (manage: boolean): Promise<CourseList> =>
    api
      .get<CourseList>('/learn/courses', { params: { manage: manage || undefined } })
      .then((r) => r.data),
  course: (id: string): Promise<CourseDetail> =>
    api.get<CourseDetail>(`/learn/courses/${id}`).then((r) => r.data),
  createCourse: (body: {
    title: string
    description?: string | null
    course_type: CourseType
    progression_mode: ProgressionMode
  }): Promise<Course> => api.post<Course>('/learn/courses', body).then((r) => r.data),
  updateCourse: (
    id: string,
    body: Partial<{
      title: string
      description: string | null
      course_type: CourseType
      progression_mode: ProgressionMode
      certificate_enabled: boolean
    }>,
  ): Promise<Course> => api.patch<Course>(`/learn/courses/${id}`, body).then((r) => r.data),
  deleteCourse: (id: string): Promise<void> =>
    api.delete(`/learn/courses/${id}`).then(() => undefined),
  setCourseStatus: (id: string, status: ContentStatus): Promise<Course> =>
    api.post<Course>(`/learn/courses/${id}/status`, { status }).then((r) => r.data),
  setCourseAudience: (
    id: string,
    body: { is_all: boolean; rules: AudienceRuleDraft[] },
  ): Promise<Course> =>
    api.put<Course>(`/learn/courses/${id}/audience`, body).then((r) => r.data),
  assignCourse: (
    id: string,
    body: { profile_ids: string[]; due_at?: string | null },
  ): Promise<Course> =>
    api.post<Course>(`/learn/courses/${id}/assign`, body).then((r) => r.data),

  createLesson: (
    courseId: string,
    body: { title: string; content_format?: LessonContentFormat },
  ): Promise<LessonMeta> =>
    api.post<LessonMeta>(`/learn/courses/${courseId}/lessons`, body).then((r) => r.data),
  updateLesson: (
    id: string,
    body: Partial<{
      title: string
      content: RichDoc
      content_format: LessonContentFormat
      pdf_media_id: string | null
      forbid_download: boolean
      unlock_rule: LessonUnlockRule
      status: 'draft' | 'published'
    }>,
  ): Promise<LessonMeta> =>
    api.patch<LessonMeta>(`/learn/lessons/${id}`, body).then((r) => r.data),
  deleteLesson: (id: string): Promise<void> =>
    api.delete(`/learn/lessons/${id}`).then(() => undefined),
  reorderLessons: (courseId: string, lessonIds: string[]): Promise<void> =>
    api
      .put(`/learn/courses/${courseId}/lessons/reorder`, { lesson_ids: lessonIds })
      .then(() => undefined),

  lesson: (id: string): Promise<LessonContent> =>
    api.get<LessonContent>(`/learn/lessons/${id}`).then((r) => r.data),
  completeLesson: (id: string): Promise<LessonContent> =>
    api.post<LessonContent>(`/learn/lessons/${id}/complete`).then((r) => r.data),
  answerBlock: (
    lessonId: string,
    blockId: string,
    answer: number,
  ): Promise<{ correct: boolean }> =>
    api
      .post<{ correct: boolean }>(`/learn/lessons/${lessonId}/blocks/${blockId}/answer`, {
        answer,
      })
      .then((r) => r.data),
  reportVideoProgress: (
    lessonId: string,
    body: { media_id: string; intervals: [number, number][]; duration: number },
  ): Promise<void> =>
    api.post(`/learn/lessons/${lessonId}/video-progress`, body).then(() => undefined),

  lessonTemplates: (): Promise<LessonTemplate[]> =>
    api.get<LessonTemplate[]>('/learn/lesson-templates').then((r) => r.data),
  createLessonTemplate: (body: { title: string; content: RichDoc }): Promise<LessonTemplate> =>
    api.post<LessonTemplate>('/learn/lesson-templates', body).then((r) => r.data),
  deleteLessonTemplate: (id: string): Promise<void> =>
    api.delete(`/learn/lesson-templates/${id}`).then(() => undefined),

  // ─── Тесты (Ф3b) ───────────────────────────────────────────────────────────
  lessonQuiz: (lessonId: string): Promise<QuizConsumer | null> =>
    api
      .get<QuizConsumer | null>(`/learn/lessons/${lessonId}/quiz`)
      .then((r) => r.data ?? null),
  lessonQuizManage: (lessonId: string): Promise<QuizManage | null> =>
    api
      .get<QuizManage | null>(`/learn/lessons/${lessonId}/quiz`, {
        params: { manage: true },
      })
      .then((r) => r.data ?? null),
  upsertLessonQuiz: (
    lessonId: string,
    body: QuizSettings & { questions: QuizQuestionDraft[] },
  ): Promise<QuizManage> =>
    api.put<QuizManage>(`/learn/lessons/${lessonId}/quiz`, body).then((r) => r.data),
  deleteQuiz: (quizId: string): Promise<void> =>
    api.delete(`/learn/quizzes/${quizId}`).then(() => undefined),
  resetQuizAttempts: (quizId: string, profileId: string): Promise<void> =>
    api
      .post(`/learn/quizzes/${quizId}/reset-attempts`, { profile_id: profileId })
      .then(() => undefined),

  startQuizAttempt: (quizId: string): Promise<QuizAttempt> =>
    api.post<QuizAttempt>(`/learn/quizzes/${quizId}/attempts`).then((r) => r.data),
  quizAttempt: (attemptId: string): Promise<QuizAttempt> =>
    api.get<QuizAttempt>(`/learn/quiz-attempts/${attemptId}`).then((r) => r.data),
  saveQuizAnswer: (attemptId: string, questionId: string, value: unknown): Promise<void> =>
    api
      .patch(`/learn/quiz-attempts/${attemptId}`, { question_id: questionId, value })
      .then(() => undefined),
  submitQuizAttempt: (attemptId: string): Promise<QuizAttempt> =>
    api.post<QuizAttempt>(`/learn/quiz-attempts/${attemptId}/submit`).then((r) => r.data),

  reviewQueue: (): Promise<ReviewQueueItem[]> =>
    api.get<ReviewQueueItem[]>('/learn/review-queue').then((r) => r.data),
  reviewQuizAttempt: (
    attemptId: string,
    scores: Record<string, number>,
  ): Promise<QuizAttempt> =>
    api
      .post<QuizAttempt>(`/learn/quiz-attempts/${attemptId}/review`, { scores })
      .then((r) => r.data),

  rating: (period: 'month' | 'quarter', scope: 'all' | 'store'): Promise<RatingData> =>
    api
      .get<RatingData>('/learn/rating', { params: { period, scope } })
      .then((r) => r.data),

  myCertificates: (): Promise<CertificateInfo[]> =>
    api.get<CertificateInfo[]>('/learn/certificates').then((r) => r.data),
  certificate: (id: string): Promise<CertificateInfo> =>
    api.get<CertificateInfo>(`/learn/certificates/${id}`).then((r) => r.data),

  // ─── Ассортимент + витрина + профиль (Ф4) ──────────────────────────────────
  products: (manage: boolean): Promise<ProductListData> =>
    api
      .get<ProductListData>('/learn/products', { params: { manage: manage || undefined } })
      .then((r) => r.data),
  createProduct: (body: ProductUpsert & { title: string }): Promise<ProductCard> =>
    api.post<ProductCard>('/learn/products', body).then((r) => r.data),
  updateProduct: (id: string, body: ProductUpsert): Promise<ProductCard> =>
    api.patch<ProductCard>(`/learn/products/${id}`, body).then((r) => r.data),
  deleteProduct: (id: string): Promise<void> =>
    api.delete(`/learn/products/${id}`).then(() => undefined),
  setProductStatus: (id: string, status: ContentStatus): Promise<ProductCard> =>
    api.post<ProductCard>(`/learn/products/${id}/status`, { status }).then((r) => r.data),
  setProductAudience: (
    id: string,
    body: { is_all: boolean; rules: AudienceRuleDraft[] },
  ): Promise<ProductCard> =>
    api.put<ProductCard>(`/learn/products/${id}/audience`, body).then((r) => r.data),
  openProduct: (id: string): Promise<void> =>
    api.post(`/learn/products/${id}/open`).then(() => undefined),
  createProductCategory: (title: string): Promise<ProductCategory> =>
    api.post<ProductCategory>('/learn/product-categories', { title }).then((r) => r.data),
  deleteProductCategory: (id: string): Promise<void> =>
    api.delete(`/learn/product-categories/${id}`).then(() => undefined),

  home: (): Promise<HomeData> => api.get<HomeData>('/learn/home').then((r) => r.data),
  learnProfile: (): Promise<LearnProfile> =>
    api.get<LearnProfile>('/learn/profile').then((r) => r.data),

  // ─── Поиск + аналитика + автосценарии (Ф5) ─────────────────────────────────
  learnSearch: (q: string): Promise<LearnSearchData> =>
    api.get<LearnSearchData>('/learn/search', { params: { q } }).then((r) => r.data),
  analytics: (): Promise<AnalyticsData> =>
    api.get<AnalyticsData>('/learn/analytics').then((r) => r.data),
  downloadAnalyticsCsv: async (): Promise<void> => {
    const resp = await api.get('/learn/analytics/export', { responseType: 'blob' })
    const url = URL.createObjectURL(resp.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'learning-report.csv'
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },

  automations: (): Promise<AutomationRule[]> =>
    api.get<AutomationRule[]>('/learn/automations').then((r) => r.data),
  createAutomation: (body: AutomationRuleUpsert): Promise<AutomationRule> =>
    api.post<AutomationRule>('/learn/automations', body).then((r) => r.data),
  updateAutomation: (id: string, body: AutomationRuleUpsert): Promise<AutomationRule> =>
    api.patch<AutomationRule>(`/learn/automations/${id}`, body).then((r) => r.data),
  deleteAutomation: (id: string): Promise<void> =>
    api.delete(`/learn/automations/${id}`).then(() => undefined),
  automationJobs: (id: string): Promise<AutomationJob[]> =>
    api.get<AutomationJob[]>(`/learn/automations/${id}/jobs`).then((r) => r.data),
  cancelAutomationJob: (jobId: string): Promise<void> =>
    api.post(`/learn/automation-jobs/${jobId}/cancel`).then(() => undefined),

  // ─── AI-помощник (Ф6) ──────────────────────────────────────────────────────
  aiStatus: (): Promise<AiStatus> =>
    api.get<AiStatus>('/learn/ai/status').then((r) => r.data),
  aiAsk: (question: string, conversationId?: string | null): Promise<AiAskResponse> =>
    api
      .post<AiAskResponse>('/learn/ai/ask', {
        question,
        conversation_id: conversationId ?? null,
      })
      .then((r) => r.data),
  aiConversations: (): Promise<AiConversation[]> =>
    api.get<AiConversation[]>('/learn/ai/conversations').then((r) => r.data),
  aiMessages: (conversationId: string): Promise<AiMessage[]> =>
    api
      .get<AiMessage[]>(`/learn/ai/conversations/${conversationId}/messages`)
      .then((r) => r.data),
  aiDeleteConversation: (conversationId: string): Promise<void> =>
    api.delete(`/learn/ai/conversations/${conversationId}`).then(() => undefined),

  uploadMedia: (file: File): Promise<MediaUploadResult> => {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<MediaUploadResult>('/learn/media', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },

  /**
   * Открыть файл материала в новой вкладке. Тег <a href> не несёт Bearer —
   * качаем blob через axios и открываем object-URL. Окно создаём ДО fetch
   * (в жесте клика), иначе попап-блокер.
   */
  openMaterialFile: async (material: LibraryMaterial): Promise<void> => {
    const win = window.open('', '_blank')
    try {
      const resp = await api.get(`/learn/library/materials/${material.id}/download`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(resp.data as Blob)
      if (win) {
        win.location.href = url
      } else {
        const a = document.createElement('a')
        a.href = url
        a.download = material.current_version?.file_name ?? material.title
        document.body.appendChild(a)
        a.click()
        a.remove()
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e) {
      win?.close()
      throw e
    }
  },
}
