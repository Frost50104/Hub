import { Navigate, Route, Routes } from 'react-router-dom'

import { Shell } from '@/components/layout/Shell'
import { AuthCallback } from '@/pages/AuthCallback'
import { HomePage } from '@/pages/HomePage'
import { InboxPage } from '@/pages/InboxPage'
import { LoginRedirect } from '@/pages/LoginRedirect'
import { MyTasksPage } from '@/pages/MyTasksPage'
import { ProjectListPage } from '@/pages/ProjectListPage'
import { ProjectPage } from '@/pages/ProjectPage'

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginRedirect />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route element={<Shell />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/my" element={<MyTasksPage />} />
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/projects" element={<ProjectListPage />} />
        <Route path="/projects/:id" element={<ProjectPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
