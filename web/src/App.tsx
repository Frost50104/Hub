import * as Sentry from '@sentry/react'
import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { ErrorFallback } from '@/components/ErrorFallback'
import { Shell } from '@/components/layout/Shell'
import { SkeletonRows } from '@/components/ui/Skeleton'
// Auth-роуты — eager: критичны для входа и крошечные.
import { AuthCallback } from '@/pages/AuthCallback'
import { LoginRedirect } from '@/pages/LoginRedirect'

// Страницы — отдельные chunk'и: тяжёлые зависимости (markdown, dnd, recharts)
// не попадают в стартовый бандл.
const HomePage = lazy(() =>
  import('@/pages/HomePage').then((m) => ({ default: m.HomePage })),
)
const InboxPage = lazy(() =>
  import('@/pages/InboxPage').then((m) => ({ default: m.InboxPage })),
)
const MyTasksPage = lazy(() =>
  import('@/pages/MyTasksPage').then((m) => ({ default: m.MyTasksPage })),
)
const ProjectListPage = lazy(() =>
  import('@/pages/ProjectListPage').then((m) => ({ default: m.ProjectListPage })),
)
const ArchivedProjectsPage = lazy(() =>
  import('@/pages/ArchivedProjectsPage').then((m) => ({ default: m.ArchivedProjectsPage })),
)
const ProjectPage = lazy(() =>
  import('@/pages/ProjectPage').then((m) => ({ default: m.ProjectPage })),
)
const PublicViewPage = lazy(() =>
  import('@/pages/PublicViewPage').then((m) => ({ default: m.PublicViewPage })),
)
const SearchPage = lazy(() =>
  import('@/pages/SearchPage').then((m) => ({ default: m.SearchPage })),
)
const SettingsPage = lazy(() =>
  import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
)
const AccountTab = lazy(() =>
  import('@/pages/settings/AccountTab').then((m) => ({ default: m.AccountTab })),
)
const AppearanceTab = lazy(() =>
  import('@/pages/settings/AppearanceTab').then((m) => ({
    default: m.AppearanceTab,
  })),
)
// Learn-пространство (LMS, Ф0+). Админ-страницы — отдельные chunk'и:
// линейный персонал их не грузит.
const LearnHomePage = lazy(() =>
  import('@/pages/learn/LearnHomePage').then((m) => ({ default: m.LearnHomePage })),
)
const LearnLibraryPage = lazy(() =>
  import('@/pages/learn/LearnLibraryPage').then((m) => ({ default: m.LearnLibraryPage })),
)
const LearnNewsPage = lazy(() =>
  import('@/pages/learn/LearnNewsPage').then((m) => ({ default: m.LearnNewsPage })),
)
const LearnSurveysPage = lazy(() =>
  import('@/pages/learn/LearnSurveysPage').then((m) => ({ default: m.LearnSurveysPage })),
)
const LearnSurveyRunPage = lazy(() =>
  import('@/pages/learn/LearnSurveysPage').then((m) => ({ default: m.LearnSurveyRunPage })),
)
const LearnCoursesPage = lazy(() =>
  import('@/pages/learn/LearnCoursesPage').then((m) => ({ default: m.LearnCoursesPage })),
)
const LearnCoursePage = lazy(() =>
  import('@/pages/learn/LearnCoursePage').then((m) => ({ default: m.LearnCoursePage })),
)
const LearnLessonPage = lazy(() =>
  import('@/pages/learn/LearnLessonPage').then((m) => ({ default: m.LearnLessonPage })),
)
const CourseBuilderPage = lazy(() =>
  import('@/pages/learn/CourseBuilderPage').then((m) => ({ default: m.CourseBuilderPage })),
)
const LearnRatingPage = lazy(() =>
  import('@/pages/learn/LearnRatingPage').then((m) => ({ default: m.LearnRatingPage })),
)
const LearnFavoritesPage = lazy(() =>
  import('@/pages/learn/LearnFavoritesPage').then((m) => ({ default: m.LearnFavoritesPage })),
)
const LearnAdminPage = lazy(() =>
  import('@/pages/learn/LearnAdminPage').then((m) => ({ default: m.LearnAdminPage })),
)
const CertificatePage = lazy(() =>
  import('@/pages/learn/CertificatePage').then((m) => ({ default: m.CertificatePage })),
)
const LearnProductsPage = lazy(() =>
  import('@/pages/learn/LearnProductsPage').then((m) => ({ default: m.LearnProductsPage })),
)
const LearnProductPage = lazy(() =>
  import('@/pages/learn/LearnProductsPage').then((m) => ({ default: m.LearnProductPage })),
)
const LearnAssessmentsPage = lazy(() =>
  import('@/pages/learn/LearnAssessmentsPage').then((m) => ({
    default: m.LearnAssessmentsPage,
  })),
)
const LearnShiftsPage = lazy(() =>
  import('@/pages/learn/LearnShiftsPage').then((m) => ({ default: m.LearnShiftsPage })),
)
const AssistantPage = lazy(() =>
  import('@/pages/AssistantPage').then((m) => ({ default: m.AssistantPage })),
)
const NotificationsSettingsTab = lazy(() =>
  import('@/pages/settings/NotificationsTab').then((m) => ({
    default: m.NotificationsSettingsTab,
  })),
)


export function App() {
  // fallback ФУНКЦИЕЙ, а не элементом: только так Sentry передаёт саму ошибку —
  // без неё экран сбоя ничего не объясняет, а Sentry в Hub ещё не подключён.
  return (
    <Sentry.ErrorBoundary fallback={({ error }) => <ErrorFallback error={error} />}>
      {/* Внешний Suspense — для роутов вне Shell (/p/:token). */}
      <Suspense fallback={<SkeletonRows rows={6} className="p-6" />}>
      <Routes>
        <Route path="/login" element={<LoginRedirect />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
        {/* /p/:token is rendered OUTSIDE Shell — no auth, anonymous. */}
        <Route path="/p/:token" element={<PublicViewPage />} />
        <Route element={<Shell />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/my" element={<MyTasksPage />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/projects" element={<ProjectListPage />} />
        {/* Статический сегмент объявлен ДО «:id»: v6 и так ранжирует по
            специфичности, но порядок здесь читается как гарантия. */}
        <Route path="/projects/archived" element={<ArchivedProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/search" element={<SearchPage />} />
          {/* Профиль слит с настройками (редизайн 2026-08): старый путь живёт
              редиректом — на него ведут таб-бар старых бандлов и закладки. */}
          <Route path="/profile" element={<Navigate to="/settings/account" replace />} />
          <Route path="/learn" element={<LearnHomePage />} />
          <Route path="/learn/library" element={<LearnLibraryPage />} />
          <Route path="/learn/news" element={<LearnNewsPage />} />
          <Route path="/learn/surveys" element={<LearnSurveysPage />} />
          <Route path="/learn/surveys/:surveyId" element={<LearnSurveyRunPage />} />
          <Route path="/learn/courses" element={<LearnCoursesPage />} />
          <Route path="/learn/courses/:courseId" element={<LearnCoursePage />} />
          <Route path="/learn/courses/:courseId/edit" element={<CourseBuilderPage />} />
          <Route path="/learn/lessons/:lessonId" element={<LearnLessonPage />} />
          <Route path="/learn/products" element={<LearnProductsPage />} />
          <Route path="/learn/products/:productId" element={<LearnProductPage />} />
          <Route path="/learn/rating" element={<LearnRatingPage />} />
          <Route path="/learn/favorites" element={<LearnFavoritesPage />} />
          {/* Ассистент общий для двух пространств. Старый learn-путь —
              редирект, а не 404: PWA живёт вчерашним бандлом. */}
          <Route path="/assistant" element={<AssistantPage />} />
          <Route
            path="/learn/assistant"
            element={<Navigate to="/assistant" replace />}
          />
          <Route path="/learn/shifts" element={<LearnShiftsPage />} />
          <Route path="/learn/assessments" element={<LearnAssessmentsPage />} />
          <Route path="/learn/certificates/:certificateId" element={<CertificatePage />} />
          {/* «Управление» — один маршрут с сегментами; старые пути живут
              редиректами навсегда: бэкенд шлёт /learn/admin/review в push,
              старые уведомления во «Входящих» хранят URL. Гейты — по сегментам
              внутри LearnAdminPage. */}
          <Route path="/learn/admin" element={<LearnAdminPage />} />
          {(['review', 'org', 'employees', 'analytics', 'automations', 'audit'] as const).map((seg) => (
            <Route
              key={seg}
              path={`/learn/admin/${seg}`}
              element={<Navigate to={`/learn/admin?tab=${seg}`} replace />}
            />
          ))}
          <Route path="/settings" element={<SettingsPage />}>
            <Route index element={<Navigate to="account" replace />} />
            <Route path="account" element={<AccountTab />} />
            <Route path="notifications" element={<NotificationsSettingsTab />} />
            <Route path="appearance" element={<AppearanceTab />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
    </Sentry.ErrorBoundary>
  )
}
