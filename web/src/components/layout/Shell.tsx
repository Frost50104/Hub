import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'

import { useIsDesktop } from '@/hooks/useMediaQuery'

import { MobileTopbar } from './MobileTopbar'
import { Sidebar } from './Sidebar'
import { SidebarDrawer } from './SidebarDrawer'

export function Shell() {
  const isDesktop = useIsDesktop()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const location = useLocation()

  // Auto-close drawer when route changes so back-button / NavLink clicks
  // don't leave the off-canvas open over the next page.
  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

  // When the viewport crosses the md breakpoint up, ensure the drawer is closed.
  useEffect(() => {
    if (isDesktop) setDrawerOpen(false)
  }, [isDesktop])

  return (
    <div className="min-h-screen md:flex md:gap-3 md:p-3">
      {isDesktop ? (
        <Sidebar />
      ) : (
        <>
          <MobileTopbar onOpenSidebar={() => setDrawerOpen(true)} />
          <SidebarDrawer open={drawerOpen} onOpenChange={setDrawerOpen} />
        </>
      )}
      <main className="min-w-0 flex-1 overflow-y-auto px-3 pb-6 pt-3 md:px-0 md:pt-0">
        <Outlet />
      </main>
    </div>
  )
}
