import * as Sentry from '@sentry/react'
import { lazy, Suspense, type ReactElement } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { ErrorFallback } from '@/components/ErrorFallback'
import { Shell } from '@/components/layout/Shell'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useMe } from '@/hooks/useMe'
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
const ProfilePage = lazy(() =>
  import('@/pages/ProfilePage').then((m) => ({ default: m.ProfilePage })),
)
const ProjectListPage = lazy(() =>
  import('@/pages/ProjectListPage').then((m) => ({ default: m.ProjectListPage })),
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
const LearnOrgPage = lazy(() =>
  import('@/pages/learn/LearnOrgPage').then((m) => ({ default: m.LearnOrgPage })),
)
const LearnEmployeesPage = lazy(() =>
  import('@/pages/learn/LearnEmployeesPage').then((m) => ({
    default: m.LearnEmployeesPage,
  })),
)
const LearnAuditPage = lazy(() =>
  import('@/pages/learn/LearnAuditPage').then((m) => ({ default: m.LearnAuditPage })),
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
const LearnReviewPage = lazy(() =>
  import('@/pages/learn/LearnReviewPage').then((m) => ({ default: m.LearnReviewPage })),
)
const CertificatePage = lazy(() =>
  import('@/pages/learn/CertificatePage').then((m) => ({ default: m.CertificatePage })),
)
const LearnProductsPage = lazy(() =>
  import('@/pages/learn/LearnProductsPage').then((m) => ({ default: m.LearnProductsPage })),
)
const NotificationsSettingsTab = lazy(() =>
  import('@/pages/settings/NotificationsTab').then((m) => ({
    default: m.NotificationsSettingsTab,
  })),
)

/** Client-гейт админ-раздела learn: сервер и так отдаёт 403 не-админам,
 * но рендерить страницу с падающими кнопками не нужно — редирект на витрину. */
function RequireHubAdmin({ children }: { children: ReactElement }) {
  const me = useMe()
  if (me.isLoading) return <SkeletonRows rows={6} className="p-6" />
  if (me.data?.hub_role !== 'admin') return <Navigate to="/learn" replace />
  return children
}

export function App() {
  return (
    <Sentry.ErrorBoundary fallback={<ErrorFallback />}>
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
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/learn" element={<LearnHomePage />} />
          <Route path="/learn/library" element={<LearnLibraryPage />} />
          <Route path="/learn/news" element={<LearnNewsPage />} />
          <Route path="/learn/surveys" element={<LearnSurveysPage />} />
          <Route path="/learn/courses" element={<LearnCoursesPage />} />
          <Route path="/learn/courses/:courseId" element={<LearnCoursePage />} />
          <Route path="/learn/courses/:courseId/edit" element={<CourseBuilderPage />} />
          <Route path="/learn/lessons/:lessonId" element={<LearnLessonPage />} />
          <Route path="/learn/products" element={<LearnProductsPage />} />
          <Route path="/learn/rating" element={<LearnRatingPage />} />
          <Route path="/learn/admin/review" element={<LearnReviewPage />} />
          <Route path="/learn/certificates/:certificateId" element={<CertificatePage />} />
          <Route
            path="/learn/admin/org"
            element={
              <RequireHubAdmin>
                <LearnOrgPage />
              </RequireHubAdmin>
            }
          />
          <Route
            path="/learn/admin/employees"
            element={
              <RequireHubAdmin>
                <LearnEmployeesPage />
              </RequireHubAdmin>
            }
          />
          <Route
            path="/learn/admin/audit"
            element={
              <RequireHubAdmin>
                <LearnAuditPage />
              </RequireHubAdmin>
            }
          />
          <Route path="/settings" element={<SettingsPage />}>
            <Route index element={<Navigate to="notifications" replace />} />
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
