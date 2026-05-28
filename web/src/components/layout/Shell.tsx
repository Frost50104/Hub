import { Outlet } from 'react-router-dom'

import { Sidebar } from './Sidebar'

export function Shell() {
  return (
    <div className="flex min-h-screen gap-3 p-3">
      <Sidebar />
      <main className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
