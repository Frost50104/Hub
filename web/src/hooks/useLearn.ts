import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import {
  type BlockedQuizItem,
  learnApi,
  type AudienceDimensionCounts,
  type AudienceDryRun,
  type AudienceRules,
  type AudienceRuleDraft,
  type AuditList,
  type CertificateInfo,
  type CourseDetail,
  type CourseList,
  type EmployeeList,
  type EmployeeProfile,
  type FavoriteItem,
  type LessonContent,
  type LessonTemplate,
  type LibraryData,
  type NewsList,
  type HomeData,
  type LearnProfile,
  type OrgSnapshot,
  type ProductListData,
  type QuizConsumer,
  type QuizManage,
  type RatingData,
  type ReviewQueueItem,
  type SurveyListData,
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

/**
 * Счётчики «сколько сотрудников» у значений пикера: «Администратор · 0».
 *
 * Справочники крошечные (единицы-десятки значений), поэтому берём разом и
 * держим свежими минуту: пикер перерисовывается на каждый клик, и запрос на
 * каждое нажатие был бы расточительством.
 */
export function useAudienceDimensionCounts(
  enabled = true,
): UseQueryResult<AudienceDimensionCounts> {
  return useQuery({
    queryKey: ['learn-audience-dimension-counts'],
    queryFn: () => learnApi.audienceDimensionCounts(),
    enabled,
    staleTime: 60_000,
    meta: { suppressGlobalError: true },
  })
}

/** Правила существующей аудитории — предзаполнение диалогов (null = «всем»). */
export function useAudienceRules(
  audienceId: string | null,
): UseQueryResult<AudienceRules> {
  return useQuery({
    queryKey: ['learn-audience-rules', audienceId],
    queryFn: () => learnApi.audienceRules(audienceId!),
    enabled: audienceId !== null,
    meta: { suppressGlobalError: true },
  })
}

// ─── Библиотека ──────────────────────────────────────────────────────────────

export function useLibrary(manage: boolean, enabled = true): UseQueryResult<LibraryData> {
  return useQuery({
    queryKey: ['learn-library', manage],
    queryFn: () => learnApi.library(manage),
    staleTime: 30_000,
    enabled,
  })
}

export function useLibraryMutation<TArgs, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
  // Заголовок тоста при ошибке. Дефолт «Не удалось сохранить изменения» врёт
  // на удалении раздела: сервер отвечает 409 «Раздел не пуст», а шапка тоста
  // говорит про сохранение — причина отказа терялась.
  errorMessage?: string,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    meta: errorMessage ? { errorMessage } : undefined,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-library'] })
    },
  })
}

// ─── Новости / Опросы / Избранное (Ф2) ───────────────────────────────────────

export function useNews(manage: boolean, enabled = true): UseQueryResult<NewsList> {
  return useQuery({
    queryKey: ['learn-news', manage],
    queryFn: () => learnApi.news(manage),
    staleTime: 30_000,
    enabled,
  })
}

export function useNewsMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-news'] })
    },
  })
}

export function useSurveys(manage: boolean, enabled = true): UseQueryResult<SurveyListData> {
  return useQuery({
    queryKey: ['learn-surveys', manage],
    queryFn: () => learnApi.surveys(manage),
    staleTime: 30_000,
    enabled,
  })
}

export function useSurveyMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-surveys'] })
    },
  })
}

export function useRecent(): UseQueryResult<FavoriteItem[]> {
  return useQuery({
    queryKey: ['learn-recent'],
    queryFn: learnApi.recent,
    staleTime: 60_000,
  })
}

export function useFavorites(): UseQueryResult<FavoriteItem[]> {
  return useQuery({
    queryKey: ['learn-favorites'],
    queryFn: learnApi.favorites,
    staleTime: 60_000,
  })
}

// ─── Курсы (Ф3a) ─────────────────────────────────────────────────────────────

export function useCourses(manage: boolean, enabled = true): UseQueryResult<CourseList> {
  return useQuery({
    queryKey: ['learn-courses', manage],
    queryFn: () => learnApi.courses(manage),
    staleTime: 30_000,
    enabled,
  })
}

export function useCourse(id: string | undefined, preview = false): UseQueryResult<CourseDetail> {
  return useQuery({
    queryKey: preview ? ['learn-course', id, 'preview'] : ['learn-course', id],
    queryFn: () => learnApi.course(id!, preview),
    enabled: Boolean(id),
  })
}

export function useLesson(id: string | undefined, preview = false): UseQueryResult<LessonContent> {
  return useQuery({
    queryKey: preview ? ['learn-lesson', id, 'preview'] : ['learn-lesson', id],
    queryFn: () => learnApi.lesson(id!, preview),
    enabled: Boolean(id),
    retry: false, // 403 «урок заперт» не лечится ретраями
    // Глобальные 30 секунд «свежести» тут вредны: ответ несёт снимок
    // прогресса видео, а плеер стартует ровно от него. Вернувшись в урок
    // сразу после выхода, человек получал устаревшие интервалы и процент
    // «откатывался» (ОС 24.08). Кэш при этом показывается мгновенно, рефетч
    // идёт фоном — скелетон не мигает.
    staleTime: 0,
    meta: { suppressGlobalError: true },
  })
}

export function useCourseMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-courses'] })
      void qc.invalidateQueries({ queryKey: ['learn-course'] })
      // Редактор урока читает ['learn-lesson', id] — без этого «глаз» в списке
      // менял статус, а редактор ниже показывал старый (ОС 2026-08).
      void qc.invalidateQueries({ queryKey: ['learn-lesson'] })
    },
  })
}

export function useLessonTemplates(enabled: boolean): UseQueryResult<LessonTemplate[]> {
  return useQuery({
    queryKey: ['learn-lesson-templates'],
    queryFn: learnApi.lessonTemplates,
    enabled,
  })
}

// ─── Тесты + рейтинг + сертификаты (Ф3b) ─────────────────────────────────────

export function useLessonQuiz(lessonId: string | undefined): UseQueryResult<QuizConsumer | null> {
  return useQuery({
    queryKey: ['learn-lesson-quiz', lessonId],
    queryFn: () => learnApi.lessonQuiz(lessonId!),
    enabled: Boolean(lessonId),
  })
}

export function useLessonQuizManage(
  lessonId: string | undefined,
): UseQueryResult<QuizManage | null> {
  return useQuery({
    queryKey: ['learn-lesson-quiz-manage', lessonId],
    queryFn: () => learnApi.lessonQuizManage(lessonId!),
    enabled: Boolean(lessonId),
  })
}

export function useQuizMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-lesson-quiz'] })
      void qc.invalidateQueries({ queryKey: ['learn-lesson-quiz-manage'] })
      void qc.invalidateQueries({ queryKey: ['learn-review-queue'] })
    },
  })
}

export function useBlockedQuizzes(enabled = true): UseQueryResult<BlockedQuizItem[]> {
  return useQuery({
    queryKey: ['learn-quizzes-blocked'],
    queryFn: learnApi.blockedQuizzes,
    enabled,
    retry: false,
    meta: { suppressGlobalError: true }, // не-publisher получает 403
  })
}

export function useReviewQueue(enabled = true): UseQueryResult<ReviewQueueItem[]> {
  return useQuery({
    queryKey: ['learn-review-queue'],
    queryFn: learnApi.reviewQueue,
    enabled,
    retry: false,
    meta: { suppressGlobalError: true }, // не-publisher получает 403
  })
}

export function useRating(
  period: 'month' | 'quarter',
  scope: 'all' | 'store',
): UseQueryResult<RatingData> {
  return useQuery({
    queryKey: ['learn-rating', period, scope],
    queryFn: () => learnApi.rating(period, scope),
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })
}

export function useMyCertificates(): UseQueryResult<CertificateInfo[]> {
  return useQuery({
    queryKey: ['learn-certificates'],
    queryFn: learnApi.myCertificates,
    staleTime: 60_000,
  })
}

// ─── Ассортимент + витрина + профиль (Ф4) ────────────────────────────────────

export function useProducts(manage: boolean, enabled = true): UseQueryResult<ProductListData> {
  return useQuery({
    queryKey: ['learn-products', manage],
    queryFn: () => learnApi.products(manage),
    staleTime: 30_000,
    enabled,
  })
}

export function useProductMutation<TArgs, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
  /** Заголовок тоста при ошибке — см. useLibraryMutation. */
  errorMessage?: string,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    meta: errorMessage ? { errorMessage } : undefined,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-products'] })
    },
  })
}

export function useLearnHome(): UseQueryResult<HomeData> {
  return useQuery({
    queryKey: ['learn-home-feed'],
    queryFn: learnApi.home,
    staleTime: 30_000,
  })
}

export function useLearnProfile(): UseQueryResult<LearnProfile> {
  return useQuery({
    queryKey: ['learn-profile'],
    queryFn: learnApi.learnProfile,
    staleTime: 60_000,
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
