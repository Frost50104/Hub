import { Navigate, Route, Routes } from 'react-router-dom'

import { Shell } from '@/components/layout/Shell'
import { AuthCallback } from '@/pages/AuthCallback'
import { LoginRedirect } from '@/pages/LoginRedirect'
import { Welcome } from '@/pages/Welcome'

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginRedirect />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route element={<Shell />}>
        <Route path="/" element={<Welcome />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
