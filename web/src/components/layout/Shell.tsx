import { Outlet } from 'react-router-dom'

import { useIsDesktop } from '@/hooks/useMediaQuery'

import { MobileBottomTabBar } from './MobileBottomTabBar'
import { Sidebar } from './Sidebar'

/**
 * Post-4.8 mobile redesign: instead of a burger + drawer like before, the
 * mobile layout (< lg / 1024px) is iOS-app-style — top bar lives inside each
 * page (`<MobilePageHeader />`), and main navigation is a fixed bottom
 * `<MobileBottomTabBar />`. iPad portrait stays mobile; landscape goes to
 * the desktop sidebar.
 *
 * `pb-20` on mobile main reserves space for the fixed bottom bar. On
 * desktop the sidebar handles spacing itself.
 */
export function Shell() {
  const isDesktop = useIsDesktop()
  return (
    <div className="min-h-screen lg:flex lg:gap-3 lg:p-3">
      {isDesktop && <Sidebar />}
      <main
        className="min-w-0 flex-1 overflow-y-auto pb-20 lg:pb-0 lg:overflow-y-auto"
        style={
          !isDesktop
            ? { paddingBottom: 'calc(env(safe-area-inset-bottom, 0) + 5rem)' }
            : undefined
        }
      >
        <Outlet />
      </main>
      {!isDesktop && <MobileBottomTabBar />}
    </div>
  )
}
