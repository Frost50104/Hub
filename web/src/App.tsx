import * as Sentry from '@sentry/react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { ErrorFallback } from '@/components/ErrorFallback'
import { Shell } from '@/components/layout/Shell'
import { AuthCallback } from '@/pages/AuthCallback'
import { HomePage } from '@/pages/HomePage'
import { InboxPage } from '@/pages/InboxPage'
import { LoginRedirect } from '@/pages/LoginRedirect'
import { MyTasksPage } from '@/pages/MyTasksPage'
import { ProjectListPage } from '@/pages/ProjectListPage'
import { ProjectPage } from '@/pages/ProjectPage'
import { PublicViewPage } from '@/pages/PublicViewPage'
import { SearchPage } from '@/pages/SearchPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { NotificationsSettingsTab } from '@/pages/settings/NotificationsTab'

export function App() {
  return (
    <Sentry.ErrorBoundary fallback={<ErrorFallback />}>
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
          <Route path="/settings" element={<SettingsPage />}>
            <Route index element={<Navigate to="notifications" replace />} />
            <Route path="notifications" element={<NotificationsSettingsTab />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Sentry.ErrorBoundary>
  )
}
