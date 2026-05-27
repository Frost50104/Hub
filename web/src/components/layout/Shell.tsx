import { Outlet } from 'react-router-dom'

import { Topbar } from './Topbar'

export function Shell() {
  return (
    <div className="flex min-h-screen flex-col">
      <Topbar />
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}
