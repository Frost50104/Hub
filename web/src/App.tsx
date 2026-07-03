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
const NotificationsSettingsTab = lazy(() =>
  import('@/pages/settings/NotificationsTab').then((m) => ({
    default: m.NotificationsSettingsTab,
  })),
)

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
