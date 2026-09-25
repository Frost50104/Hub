import { api } from './api'
// Строка прогресса объявлена рядом с правилами экрана (`learnProgress.ts`):
// тип и логика, которая его читает, обязаны меняться вместе.
import type { AuthState } from './authState'
import type { EmployeeProgressRow } from './learnProgress'
import { materialDownloadName } from './materialFileName'
import { parseEcho, type VideoProgressEcho } from './videoWatch'
import type { HrSyncReport, HrView } from './hrLock'

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
  // Ссылка на объект реестра auth (0053); с 19.09 пишется через POST/PATCH.
  site_id: string | null
}

/** Строка зеркала реестра объектов (shadow_sites); только чтение, только admin. */
export interface SiteMirror {
  site_id: string
  code: string | null
  name: string
  address: string | null
  legal_name: string | null
  inn: string | null
  email: string | null
  phone: string | null
  archived_at: string | null
  synced_at: string
}

/** Объект реестра без карточки, который автоматика не завела сама (19.09). */
export interface SitePending {
  site_id: string
  code: string | null
  name: string
  address: string | null
  iiko_ref: string | null
  reason: 'no_iiko_ref' | 'code_collision' | 'name_collision'
  candidate_store_id: string | null
  candidate_store_name: string | null
}

/** Слияние карточек одного объекта реестра (19.09): что перейдёт от проигравшей. */
export interface MergePreview {
  loser_id: string
  winner_id: string
  recommended_winner_id: string
  counts: Record<string, number>
}

export interface MergeResult {
  loser_id: string
  winner_id: string
  counts: Record<string, number>
}

export interface SitesResponse {
  items: SiteMirror[]
  snapshot_fresh: boolean
}

export interface OrgDepartment {
  id: string
  name: string
  parent_id: string | null
  /** 0063: отделы архивирует auth (16d). Необязательное — старый бэкенд поля не шлёт. */
  archived_at?: string | null
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
  /**
   * Кадровые данные ведутся в auth (16d). Нет поля или `null` — правка в Hub,
   * как раньше (старый бэкенд — тоже «не заморожено»).
   */
  hr?: HrView | null
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
  /** `service` — касса точки: карточка живёт, но учеником не является (0056). */
  account_kind: 'person' | 'service'
  org_role: OrgRole
  content_role: ContentRole
  hired_at: string | null
  status_text: string | null
  status: 'active' | 'archived'
  archived_at: string | null
  archive_reason: string | null
  last_activity_at: string | null
  created_at: string
  /**
   * Архивная карточка с тем же email. Приходит ТОЛЬКО из одиночной ручки
   * (`learnApi.employee`), в списке всегда `null`: подсказка редкая, а запрос
   * на строку — нет.
   */
  archived_twin?: { id: string; full_name: string; archived_at: string | null } | null
  /** Закреплённые магазины (только для org_role=tu). */
  tu_store_ids: string[]
  /** Кеш из auth (staff-sync, 0052): hub-роль и честный статус учётки. */
  hub_role?: string | null
  auth_state?: string | null
  /** Кадровые поля ведёт auth (16d): считает сервер, у касс всегда false. */
  hr_locked?: boolean
}

/** Непринятое приглашение с ролью hub — «добавлен, но ещё не входил». */
export interface AuthInvitation {
  id: string
  email: string
  full_name: string | null
  role: string
  expires_at: string | null
}

export interface EmployeeList {
  items: EmployeeProfile[]
  total: number
  /** Когда штат синкался из auth; null = auth ещё не выкатил ручку. */
  staff_synced_at?: string | null
  /** Только для hub-admin; остальным приходит пустым. */
  invitations?: AuthInvitation[]
}

export interface StaffSyncReport {
  available: boolean
  // true = подсчёт без записи: сервер форсит его, пока staff-sync выключен
  dry_run: boolean
  shadows: number
  profiles_created: number
  profiles_linked: number
  email_conflicts: number
  archived_skips: number
  service_accounts: number
  inactive_skipped: number
  roles_cleared: number
  archived: number
  invitations: number
  /** Кадровые данные из auth (16d): отчёт только своей организации. */
  hr?: HrSyncReport | null
}

/** Отложенный набор предохранителя (16d) — «Посмотреть и применить». */
export interface HrPending {
  fingerprint: string
  since: string | null
  reason: string | null
  cards: number
  mandatory: number
  fields: Record<string, number>
  items: Array<{
    id: string
    full_name: string
    changes: Array<{ field: string; old: string | null; new: string | null }>
  }>
  archive: Array<{ id: string; full_name: string }>
  returns: Array<{ id: string; full_name: string }>
  directory: Array<{ kind: string; action: string; name: string | null; value: string | null }>
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

/** Отчёт CSV-импорта (update-only с 16.09): карточки не создаются. */
export interface ImportReport {
  updated: number
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
  /** «Контур» (org_role): employee | tu | franchisee_owner | office. */
  org_roles: string[]
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
    org_roles: [],
  }
}

/** Тело PUT .../audience и dry-run: три состояния — «всем» (is_all без
 *  правил), «никому» (is_none — оверлей, правила сохраняются), «по правилам». */
export interface AudiencePayload {
  is_all: boolean
  is_none: boolean
  rules: AudienceRuleDraft[]
}

export interface AudienceDryRun {
  count: number
  sample: { id: string; full_name: string }[]
}

/** Сколько активных сотрудников стоит за каждым значением измерения пикера.
 *  Значения, за которыми никого нет, в ответе отсутствуют — клиент рисует
 *  у них ноль сам. */
export interface AudienceDimensionCounts {
  counts: Record<string, Record<string, number>>
}

/** Ответ GET /learn/audiences/{id} — предзаполнение пикера аудитории. */
export interface AudienceRules {
  is_all: boolean
  /** «Скрыто ото всех» (0051) — сеется в черновик вместе с правилами. */
  is_none: boolean
  rules: AudienceRuleDraft[]
  /** Имена по profile_ids правил (включая архивных) — для чипов. */
  profile_labels: Record<string, string>
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
  /** Есть извлечённый текст — «Просмотреть текст» для docx/xlsx. */
  has_text: boolean
}

export interface MaterialText {
  version_no: number
  mime: string
  text: string
  truncated: boolean
}

/** Тупик «лимит попыток обязательного теста исчерпан» (GET /learn/quizzes/blocked). */
export interface BlockedQuizItem {
  quiz_id: string
  quiz_title: string
  course_id: string | null
  lesson_id: string | null
  profile_id: string
  employee_name: string
  attempts_used: number
  attempts_limit: number
  last_attempt_at: string | null
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
  /** Готовый подписанный адрес скачивания (без Bearer) — открывается
   *  window.open'ом прямо в жесте клика: iOS standalone-PWA не скриптует
   *  окно после window.open(''), белый about:blank (ОС 02.09). */
  download_url: string | null
  opened_by_me: boolean
  acked_by_me: boolean
  ack_pending: boolean
  /** Дедлайн ознакомления лично для меня: max(публикация, выдача доступа) + дни. */
  ack_deadline_at: string | null
}

export interface LibraryData {
  sections: LibrarySection[]
  materials: LibraryMaterial[]
  content_role: 'admin' | 'publisher' | 'author' | 'none'
}

export interface MaterialUpsert {
  title?: string
  description?: string | null
  /** Тип можно менять и при редактировании (02.09) — сервер пересчитает
   *  url/current_version_no и эффективную ack-версию. */
  kind?: 'file' | 'link'
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
  /** false — объект снят с публикации: строка есть, ссылки нет. */
  available: boolean
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
  estimated_minutes: number
  has_quiz: boolean
  has_check_question: boolean
  /** Кто держит замок — считает сервер: клиент не знает, урок это или тест. */
  blocked_by_id: string | null
  blocked_by_title: string | null
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
  /** Агрегаты шапки курса — приходят только из детальной ручки. */
  quizzes_total: number
  estimated_minutes_total: number
}

export interface CourseList {
  items: Course[]
  content_role: 'admin' | 'publisher' | 'author' | 'none'
}

export interface CourseDetail extends Course {
  lessons: LessonMeta[]
}

export interface LessonBlockState {
  answers?: Record<string, { answer: number; correct: boolean }>
  /** duration = null: длительность не смог измерить ни сервер (битый moov),
   *  ни клиент. Гейт в этом случае честно говорит, что завершение недоступно. */
  video?: Record<string, { intervals: [number, number][]; duration: number | null }>
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
  /** Обязательный опубликованный тест урока и его состояние (сервер, quiz_gate):
   *  без `passed` урок не завершить. */
  quiz_required: boolean
  quiz_state:
    | 'none'
    | 'not_started'
    | 'in_progress'
    | 'failed'
    | 'pending_review'
    | 'limit_exhausted'
    | 'passed'
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
  /** Подписанный URL фирменной подложки; null — типографский лист. */
  background_url: string | null
  /** «Бариста · Галерея» — должность и магазин владельца на момент чтения (только в GET одного сертификата). */
  role_title?: string | null
  lessons_count?: number
  best_score_pct?: number | null
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
    /** Есть только у карточек ассортимента — у остального фото не бывает. */
    image_url: string | null
  }[]
  surveys: {
    id: string
    title: string
    kind: string
    closes_at: string | null
    question_count: number
    is_anonymous: boolean
  }[]
  rating: {
    points: number
    rank: number | null
    total_participants: number
    delta_week: number
  } | null
  assessments: {
    id: string
    title: string
    ends_at: string | null
    question_count: number
  }[]
}

/** Тип контента в лентах витрины («Новинки»/«Недавнее») — иначе товар,
 * курс и документ неразличимы в списке голых заголовков. */
export const CONTENT_TYPE_LABEL: Record<string, string> = {
  course: 'Курс',
  lesson: 'Урок',
  material: 'Документ',
  library_material: 'Документ',
  news: 'Новость',
  news_post: 'Новость',
  survey: 'Опрос',
  product: 'Товар',
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

// ─── Прогресс обучения по сотрудникам ────────────────────────────────────────

export type { EmployeeProgressRow }

/** Строка прогресса. Тип строки списка и шапки панели — намеренно один. */
export interface EmployeeProgressSummary {
  people: number
  without_account: number
  never_active: number
  completed_all: number
  completed_none: number
  mandatory_total: number
  mandatory_done: number
  mandatory_pct: number | null
}

export interface EmployeeProgressList {
  scope: string
  total: number
  /** Упёрлись в серверный потолок — подпись обязана сказать об этом вслух. */
  truncated: boolean
  summary: EmployeeProgressSummary
  items: EmployeeProgressRow[]
}

export interface EmployeeProgressCourse {
  course_id: string
  title: string
  course_type: CourseType
  course_status: string
  required: boolean
  /** audience | assignment | progress_only (последнее — снятый с публикации). */
  source: string
  status: 'not_started' | 'in_progress' | 'completed'
  lessons_total: number
  lessons_completed: number
  started_at: string | null
  completed_at: string | null
  due_at: string | null
  certificate_serial: string | null
}

export interface EmployeeProgressAttempt {
  attempt_id: string
  quiz_title: string
  attempt_no: number
  finished_at: string | null
  score_pct: number | null
  state: 'in_progress' | 'pending_review' | 'passed' | 'failed'
}

export interface EmployeeProgressDetail {
  profile: EmployeeProgressRow
  courses: EmployeeProgressCourse[]
  attempts: EmployeeProgressAttempt[]
}

/** Учётка точки — касса за планшетом в зале (0056). */
export interface PointAccount {
  profile_id: string
  store_id: string | null
  full_name: string
  email: string
  auth_state: AuthState
  last_activity_at: string | null
  archived: boolean
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

// ─── Биржа смен (Ф7) ─────────────────────────────────────────────────────────

export type ShiftStatus = 'open' | 'assigned' | 'done' | 'cancelled'
export type ShiftApplicationStatus = 'pending' | 'accepted' | 'declined' | 'withdrawn'

export const SHIFT_STATUS_LABEL: Record<ShiftStatus, string> = {
  open: 'Открыта',
  assigned: 'Назначена',
  done: 'Завершена',
  cancelled: 'Отменена',
}

export interface ShiftApplicationView {
  id: string
  profile_id: string
  employee_name: string | null
  position_name: string | null
  status: ShiftApplicationStatus
  comment: string | null
  created_at: string
  /** Все required-курсы смены у кандидата завершены (сервер считает при отдаче). */
  passed_required: boolean
}

export interface ShiftCourseRef {
  id: string
  title: string
}

export interface ShiftPosting {
  id: string
  store_id: string
  store_name: string | null
  position_id: string
  position_name: string | null
  starts_at: string
  ends_at: string
  pay_note: string | null
  note: string | null
  required_course_ids: string[]
  required_course_titles: string[]
  auto_confirm: boolean
  status: ShiftStatus
  assigned_profile_id: string | null
  assigned_name: string | null
  created_at: string
  my_application_status: ShiftApplicationStatus | null
  can_apply: boolean
  /** Названия недостающих курсов (legacy); `missing` — те же курсы с id для «К курсу». */
  missing_courses: string[]
  missing: ShiftCourseRef[]
  applications: ShiftApplicationView[] | null
}

export interface ShiftListData {
  items: ShiftPosting[]
  can_manage: boolean
  /** Должность текущего сотрудника — подпись «моя должность — …» в шапке. */
  my_position_name: string | null
}

export interface ShiftPostingUpdate {
  starts_at?: string
  ends_at?: string
  pay_note?: string | null
  note?: string | null
  required_course_ids?: string[]
  auto_confirm?: boolean
}

export interface ShiftPostingCreate {
  store_id: string
  position_id: string
  starts_at: string
  ends_at: string
  pay_note?: string | null
  note?: string | null
  required_course_ids?: string[]
  auto_confirm?: boolean
}

// ─── Аттестации (Ф8) ─────────────────────────────────────────────────────────

export type CampaignStatus = 'draft' | 'active' | 'closed'

export const CAMPAIGN_STATUS_LABEL: Record<CampaignStatus, string> = {
  draft: 'Черновик',
  active: 'Идёт',
  closed: 'Закрыта',
}

export interface AssessmentCampaign {
  id: string
  title: string
  description: string | null
  audience_id: string | null
  starts_at: string | null
  ends_at: string | null
  status: CampaignStatus
  quiz_id: string | null
  question_count: number
  created_at: string
  my_state: QuizConsumer | null
  audience_size: number
  /** Аудитория «скрыто ото всех» — бейдж на карточке объясняет «0 из 0». */
  audience_hidden: boolean
  completed_count: number
  /** ВСЕ попытки по тесту кампании, без пересечения с аудиторией: именно
   *  столько результатов уничтожит удаление. `completed_count` для этого не
   *  годится — он считает только тех, кто в аудитории сейчас. */
  attempt_count: number
}

export interface AssessmentReportRow {
  profile_id: string
  full_name: string
  status: 'not_started' | 'in_progress' | 'pending_review' | 'passed' | 'failed'
  score_pct: number | null
  finished_at: string | null
  /** Лучшая завершённая попытка (её балл и показан) — хендл разбора ответов. */
  attempt_id: string | null
}

/** «Сложные вопросы»: доля ошибок по вопросу среди всех сдававших. */
export interface AssessmentQuestionStat {
  prompt: string
  qtype: QuizQuestionType
  attempts: number
  wrong: number
  fail_rate_pct: number
}

export interface AssessmentReport {
  campaign_id: string
  title: string
  rows: AssessmentReportRow[]
  /** Только hub-admin; null — сервер не считал. */
  question_stats: AssessmentQuestionStat[] | null
}

/** Разбор попытки из отчёта (admin-only): ответы человека + правильные. */
export interface AssessmentAttemptDetail {
  attempt_id: string
  profile_id: string
  employee_name: string
  attempt_no: number
  finished_at: string | null
  score_pct: number | null
  passed: boolean | null
  needs_review: boolean
  questions: QuizSnapshotQuestion[]
  answers: Record<string, unknown>
  results: Record<string, boolean | null>
  correct_answers: Record<string, Record<string, unknown>>
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
  sites: (): Promise<SitesResponse> =>
    api.get<SitesResponse>('/learn/sites').then((r) => r.data),
  sitesPending: (): Promise<{ items: SitePending[] }> =>
    api.get<{ items: SitePending[] }>('/learn/sites/pending').then((r) => r.data),
  mergeStorePreview: (loserId: string, winnerId: string): Promise<MergePreview> =>
    api
      .get<MergePreview>(`/learn/org/stores/${loserId}/merge-preview`, { params: { into: winnerId } })
      .then((r) => r.data),
  mergeStore: (loserId: string, winnerId: string): Promise<MergeResult> =>
    api.post<MergeResult>(`/learn/org/stores/${loserId}/merge`, { into: winnerId }).then((r) => r.data),

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
    site_id?: string | null
  }): Promise<OrgStore> => api.post<OrgStore>('/learn/org/stores', body).then((r) => r.data),
  updateStore: (
    id: string,
    body: Partial<{
      name: string
      code: string | null
      address: string | null
      franchisee_id: string | null
      archived: boolean
      site_id: string | null
    }>,
  ): Promise<OrgStore> =>
    api.patch<OrgStore>(`/learn/org/stores/${id}`, body).then((r) => r.data),
  deleteStore: (id: string): Promise<void> =>
    api.delete(`/learn/org/stores/${id}`).then(() => undefined),

  createDepartment: (body: { name: string; parent_id?: string | null }): Promise<OrgDepartment> =>
    api.post<OrgDepartment>('/learn/org/departments', body).then((r) => r.data),
  updateDepartment: (
    id: string,
    // `archived` — вернуть отдел из архива после отката организации (16d):
    // архив отделов ведёт auth, пока организация заморожена.
    body: Partial<{ name: string; parent_id: string | null; archived: boolean }>,
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
  /** Ручной прогон staff-sync — кнопка «Обновить из auth» (admin). */
  syncStaff: (): Promise<StaffSyncReport> =>
    api.post<StaffSyncReport>('/learn/employees/sync').then((r) => r.data),
  updateEmployee: (id: string, body: EmployeeUpsert & { status_text?: string | null }): Promise<EmployeeProfile> =>
    api.patch<EmployeeProfile>(`/learn/employees/${id}`, body).then((r) => r.data),
  /** Что держит предохранитель кадровых данных; null — ничего. */
  hrPending: (): Promise<HrPending | null> =>
    api.get<HrPending | null>('/learn/employees/hr/pending').then((r) => r.data),
  applyHrPending: (fingerprint: string): Promise<{ report: HrSyncReport }> =>
    api
      .post<{ report: HrSyncReport }>('/learn/employees/hr/apply-pending', { fingerprint })
      .then((r) => r.data),
  replaceTuStores: (id: string, storeIds: string[]): Promise<EmployeeProfile> =>
    api
      .put<EmployeeProfile>(`/learn/employees/${id}/tu-stores`, { store_ids: storeIds })
      .then((r) => r.data),
  // Архивация ОСВОБОЖДАЕТ вход и корпоративный ящик: следующий сотрудник на том
  // же адресе получит чистую карточку. Причину не выбираем — у человека вариант
  // один, и спрашивать значило бы дать возможность ответить неверно.
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

  audienceDryRun: (body: AudiencePayload): Promise<AudienceDryRun> =>
    api.post<AudienceDryRun>('/learn/audiences/dry-run', body).then((r) => r.data),
  audienceDimensionCounts: (): Promise<AudienceDimensionCounts> =>
    api
      .get<AudienceDimensionCounts>('/learn/audiences/dimension-counts')
      .then((r) => r.data),
  audienceRebuild: (): Promise<{ audiences_changed: number }> =>
    api.post<{ audiences_changed: number }>('/learn/audiences/rebuild').then((r) => r.data),
  audienceRules: (audienceId: string): Promise<AudienceRules> =>
    api.get<AudienceRules>(`/learn/audiences/${audienceId}`).then((r) => r.data),

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
  setSectionAudience: (
    id: string,
    body: AudiencePayload,
  ): Promise<LibrarySection> =>
    api
      .put<LibrarySection>(`/learn/library/sections/${id}/audience`, body)
      .then((r) => r.data),
  // force — перенести материалы/подразделы в «Без раздела» и удалить.
  deleteSection: (id: string, force = false): Promise<void> =>
    api
      .delete(`/learn/library/sections/${id}`, { params: { force: force || undefined } })
      .then(() => undefined),
  materialText: (id: string): Promise<MaterialText> =>
    api.get<MaterialText>(`/learn/library/materials/${id}/text`).then((r) => r.data),

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
    body: AudiencePayload,
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
      /** Закрепление: ISO-дата «до» или null = открепить (сортировка — на сервере). */
      pinned_until: string | null
    }>,
  ): Promise<NewsPost> => api.patch<NewsPost>(`/learn/news/${id}`, body).then((r) => r.data),
  deleteNews: (id: string): Promise<void> =>
    api.delete(`/learn/news/${id}`).then(() => undefined),
  setNewsStatus: (id: string, status: ContentStatus): Promise<NewsPost> =>
    api.post<NewsPost>(`/learn/news/${id}/status`, { status }).then((r) => r.data),
  setNewsAudience: (
    id: string,
    body: AudiencePayload,
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
    body: AudiencePayload,
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
  // Только ключи «тип:id»: без лимита и без индекса публикаций — см. ручку.
  favoriteIds: (): Promise<string[]> =>
    api.get<{ keys: string[] }>('/learn/favorites/ids').then((r) => r.data.keys),
  recent: (): Promise<FavoriteItem[]> =>
    api.get<FavoriteItem[]>('/learn/recent').then((r) => r.data),

  // ─── Курсы (Ф3a) ───────────────────────────────────────────────────────────
  courses: (manage: boolean): Promise<CourseList> =>
    api
      .get<CourseList>('/learn/courses', { params: { manage: manage || undefined } })
      .then((r) => r.data),
  course: (id: string, preview = false): Promise<CourseDetail> =>
    api
      .get<CourseDetail>(`/learn/courses/${id}`, { params: { preview: preview || undefined } })
      .then((r) => r.data),
  /** Дубликат черновиком (уроки + тесты, без назначений/аудитории). */
  duplicateCourse: (id: string): Promise<Course> =>
    api.post<Course>(`/learn/courses/${id}/duplicate`).then((r) => r.data),
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
    body: AudiencePayload,
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
  /** Порядок каталога курсов — перенумерация ВСЕГО списка (publisher+). */
  reorderCourses: (courseIds: string[]): Promise<void> =>
    api.put('/learn/courses/reorder', { course_ids: courseIds }).then(() => undefined),
  reorderLessons: (courseId: string, lessonIds: string[]): Promise<void> =>
    api
      .put(`/learn/courses/${courseId}/lessons/reorder`, { lesson_ids: lessonIds })
      .then(() => undefined),

  // preview — «глазами сотрудника»: сервер считает замки и next_locked как
  // для обычного профиля, даже если зовёт автор/админ (QA-0821 #18).
  lesson: (id: string, preview = false): Promise<LessonContent> =>
    api
      .get<LessonContent>(`/learn/lessons/${id}`, { params: { preview: preview || undefined } })
      .then((r) => r.data),
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
  /** Отдаёт СЕРВЕРНОЕ покрытие: своей копии формулы у клиента больше нет.
   *  `null` — старый бэкенд ещё отвечает 204 (окно deploy.sh). */
  reportVideoProgress: (
    lessonId: string,
    body: { media_id: string; intervals: [number, number][]; duration: number | null },
  ): Promise<VideoProgressEcho | null> =>
    api
      .post(`/learn/lessons/${lessonId}/video-progress`, body)
      .then((r) => parseEcho(r.data)),

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

  blockedQuizzes: (): Promise<BlockedQuizItem[]> =>
    api.get<BlockedQuizItem[]>('/learn/quizzes/blocked').then((r) => r.data),
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
  /** Подложка сертификата — общая для тенанта, ставит hub-admin. */
  setCertificateBackground: (mediaId: string | null): Promise<{ background_url: string | null }> =>
    api
      .put<{ background_url: string | null }>('/learn/certificate-background', {
        media_id: mediaId,
      })
      .then((r) => r.data),

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
    body: AudiencePayload,
  ): Promise<ProductCard> =>
    api.put<ProductCard>(`/learn/products/${id}/audience`, body).then((r) => r.data),
  openProduct: (id: string): Promise<void> =>
    api.post(`/learn/products/${id}/open`).then(() => undefined),
  createProductCategory: (title: string): Promise<ProductCategory> =>
    api.post<ProductCategory>('/learn/product-categories', { title }).then((r) => r.data),
  renameProductCategory: (id: string, title: string): Promise<ProductCategory> =>
    api
      .patch<ProductCategory>(`/learn/product-categories/${id}`, { title })
      .then((r) => r.data),
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
  pointAccounts: (): Promise<PointAccount[]> =>
    api.get<PointAccount[]>('/learn/org/points/accounts').then((r) => r.data),
  employeeProgress: (params: {
    q?: string
    store_id?: string
    position_id?: string
  }): Promise<EmployeeProgressList> =>
    api
      .get<EmployeeProgressList>('/learn/analytics/employees', { params })
      .then((r) => r.data),
  employeeProgressDetail: (profileId: string): Promise<EmployeeProgressDetail> =>
    api
      .get<EmployeeProgressDetail>(`/learn/analytics/employees/${profileId}`)
      .then((r) => r.data),
  /** «Напомнить неознакомленным» — батч library.ack_required по отчёту об ознакомлении. */
  remindMaterial: (id: string): Promise<{ notified: number; pending: number }> =>
    api
      .post<{ notified: number; pending: number }>(`/learn/library/materials/${id}/remind`)
      .then((r) => r.data),
  /** CSV результатов опроса — из тех же агрегатов с k-анонимностью, что и экран. */
  downloadSurveyCsv: async (id: string, dimension?: string): Promise<void> => {
    const resp = await api.get(`/learn/surveys/${id}/results.csv`, {
      params: { dimension: dimension || undefined },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(resp.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'survey-results.csv'
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },
  downloadAnalyticsCsv: async (params: {
    q?: string
    store_id?: string
    position_id?: string
  } = {}): Promise<void> => {
    const resp = await api.get('/learn/analytics/export', {
      params,
      responseType: 'blob',
    })
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

  // ─── Биржа смен (Ф7) ───────────────────────────────────────────────────────
  shifts: (manage: boolean): Promise<ShiftListData> =>
    api
      .get<ShiftListData>('/learn/shifts', { params: { manage: manage || undefined } })
      .then((r) => r.data),
  createShift: (body: ShiftPostingCreate): Promise<ShiftPosting> =>
    api.post<ShiftPosting>('/learn/shifts', body).then((r) => r.data),
  applyShift: (id: string, comment?: string): Promise<void> =>
    api.post(`/learn/shifts/${id}/apply`, { comment: comment || null }).then(() => undefined),
  withdrawShift: (id: string): Promise<void> =>
    api.post(`/learn/shifts/${id}/withdraw`).then(() => undefined),
  acceptShiftApplication: (applicationId: string): Promise<void> =>
    api.post(`/learn/shift-applications/${applicationId}/accept`).then(() => undefined),
  declineShiftApplication: (applicationId: string): Promise<void> =>
    api.post(`/learn/shift-applications/${applicationId}/decline`).then(() => undefined),
  updateShift: (id: string, body: ShiftPostingUpdate): Promise<ShiftPosting> =>
    api.patch<ShiftPosting>(`/learn/shifts/${id}`, body).then((r) => r.data),
  cancelShift: (id: string): Promise<void> =>
    api.post(`/learn/shifts/${id}/cancel`).then(() => undefined),
  completeShift: (id: string): Promise<void> =>
    api.post(`/learn/shifts/${id}/complete`).then(() => undefined),

  // ─── Аттестации (Ф8) ───────────────────────────────────────────────────────
  assessments: (): Promise<AssessmentCampaign[]> =>
    api.get<AssessmentCampaign[]>('/learn/assessments').then((r) => r.data),
  createAssessment: (body: {
    title: string
    description?: string | null
    starts_at?: string | null
    ends_at?: string | null
  }): Promise<AssessmentCampaign> =>
    api.post<AssessmentCampaign>('/learn/assessments', body).then((r) => r.data),
  updateAssessment: (
    id: string,
    body: {
      title: string
      description?: string | null
      starts_at?: string | null
      ends_at?: string | null
    },
  ): Promise<AssessmentCampaign> =>
    api.patch<AssessmentCampaign>(`/learn/assessments/${id}`, body).then((r) => r.data),
  setAssessmentAudience: (
    id: string,
    body: AudiencePayload,
  ): Promise<void> =>
    api.put(`/learn/assessments/${id}/audience`, body).then(() => undefined),
  assessmentQuiz: (id: string): Promise<QuizManage> =>
    api.get<QuizManage>(`/learn/assessments/${id}/quiz`).then((r) => r.data),
  upsertAssessmentQuiz: (
    id: string,
    body: QuizSettings & { questions: QuizQuestionDraft[] },
  ): Promise<QuizManage> =>
    api.put<QuizManage>(`/learn/assessments/${id}/quiz`, body).then((r) => r.data),
  importAssessmentQuestions: (id: string, quizId: string): Promise<QuizManage> =>
    api
      .post<QuizManage>(`/learn/assessments/${id}/import-questions`, { quiz_id: quizId })
      .then((r) => r.data),
  activateAssessment: (id: string): Promise<void> =>
    api.post(`/learn/assessments/${id}/activate`).then(() => undefined),
  closeAssessment: (id: string): Promise<void> =>
    api.post(`/learn/assessments/${id}/close`).then(() => undefined),
  deleteAssessment: (id: string): Promise<void> =>
    api.delete(`/learn/assessments/${id}`).then(() => undefined),
  assessmentReport: (id: string): Promise<AssessmentReport> =>
    api.get<AssessmentReport>(`/learn/assessments/${id}/report`).then((r) => r.data),
  assessmentAttempt: (
    campaignId: string,
    attemptId: string,
  ): Promise<AssessmentAttemptDetail> =>
    api
      .get<AssessmentAttemptDetail>(
        `/learn/assessments/${campaignId}/attempts/${attemptId}`,
      )
      .then((r) => r.data),

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
   * Скачать файл материала для показа внутри приложения.
   *
   * Тот же эндпоинт, что и «скачать»: он отмечает открытие (`_track_open`),
   * а по этой отметке стоит гейт кнопки «Ознакомлен» — обходить его отдельной
   * ручкой нельзя.
   *
   * Отдаём И байты, И object-URL: pdf.js читает байты напрямую (blob-URL он
   * тянет XHR'ом, а `connect-src` в CSP не содержит `blob:` — запрос падает),
   * а <img> в лайтбоксе показывает object-URL (`img-src` blob: разрешает).
   * Освобождать URL обязан вызывающий.
   */
  materialFile: async (
    materialId: string,
  ): Promise<{ bytes: Uint8Array; objectUrl: string }> => {
    const resp = await api.get(`/learn/library/materials/${materialId}/download`, {
      responseType: 'blob',
    })
    const blob = resp.data as Blob
    return {
      bytes: new Uint8Array(await blob.arrayBuffer()),
      objectUrl: URL.createObjectURL(blob),
    }
  },

  /**
   * Открыть файл материала в новой вкладке. Тег <a href> не несёт Bearer —
   * берём у сервера короткоживущий ПОДПИСАННЫЙ адрес и ведём окно на него.
   * Окно создаём ДО fetch (в жесте клика), иначе попап-блокер.
   *
   * Именно подписанный https, а НЕ blob: iOS standalone PWA открывает
   * window.open оверлеем about:blank, который на blob-URL не переходит —
   * «Скачать файл» упирался в белый экран (ОС 02.09). Учёт открытия
   * (ack-гейт) сервер делает при выдаче ссылки.
   */
  openMaterialFile: async (material: LibraryMaterial): Promise<void> => {
    const win = window.open('', '_blank')
    try {
      const resp = await api.get<{ url: string }>(
        `/learn/library/materials/${material.id}/download-link`,
      )
      const url = resp.data.url
      if (win) {
        win.location.href = url
      } else {
        const a = document.createElement('a')
        a.href = url
        // Не сырое `file_name`: в колонке встречается голое «xlsx».
        a.download = materialDownloadName(material)
        document.body.appendChild(a)
        a.click()
        a.remove()
      }
    } catch (e) {
      win?.close()
      throw e
    }
  },
}
