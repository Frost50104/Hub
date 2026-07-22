import { LogOut, ShieldOff } from 'lucide-react'
import { Suspense, useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'

import { Button } from '@/components/ui/Button'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import { authClient } from '@/lib/auth'
import { spaceFromPath, useWorkspace } from '@/lib/workspace'

import { LearnSidebar } from './LearnSidebar'
import { MobileBottomTabBar } from './MobileBottomTabBar'
import { Sidebar } from './Sidebar'

/** Signaris-аккаунт без hub-роли (например, юзер только Desk): раньше UI
 * рендерил пустое приложение с тихими 403 — показываем явный экран. */
function NoAccessScreen() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
      <ShieldOff className="h-10 w-10 text-text3" />
      <h1 className="font-display text-xl font-semibold text-text">
        Нет доступа к Hub
      </h1>
      <p className="max-w-sm text-sm text-text2">
        Вашему аккаунту не выдана роль в продукте Hub. Обратитесь к
        администратору Signaris, чтобы получить доступ.
      </p>
      <Button variant="secondary" onClick={() => void authClient.logout()}>
        <LogOut className="h-4 w-4" /> Выйти
      </Button>
    </div>
  )
}

/**
 * Post-4.8 mobile redesign: instead of a burger + drawer like before, the
 * mobile layout (< lg / 1024px) is iOS-app-style — top bar lives inside each
 * page (`<MobilePageHeader />`), and main navigation is a fixed bottom
 * `<MobileBottomTabBar />`. iPad portrait stays mobile; landscape goes to
 * the desktop sidebar.
 *
 * Два пространства (Ф0 LMS): «Задачи» и «Обучение» (/learn/*). Пространство
 * выводится из URL; Shell лишь выбирает нужный Sidebar/набор табов и
 * запоминает последний выбор для будущих сессий.
 *
 * `pb-20` on mobile main reserves space for the fixed bottom bar. On
 * desktop the sidebar handles spacing itself.
 *
 * Скролл-инвариант (desktop, ≥lg): корень — `h-screen overflow-hidden`,
 * скроллится ТОЛЬКО `<main>`. Иначе (как было до 2026-07-22) документ
 * скроллится целиком и сайдбар с профилем уезжает за верхний край экрана.
 * Мобильный layout не трогаем — там скроллится документ.
 */
export function Shell() {
  const isDesktop = useIsDesktop()
  const location = useLocation()
  const space = spaceFromPath(location.pathname)
  const rememberSpace = useWorkspace((s) => s.rememberSpace)
  const me = useMe()

  useEffect(() => {
    rememberSpace(space)
  }, [space, rememberSpace])

  // Только при ЗАГРУЖЕННОМ /api/me — иначе экран мигал бы у всех на старте.
  if (me.data && me.data.hub_role === null) return <NoAccessScreen />

  return (
    <div className="min-h-screen lg:flex lg:h-screen lg:gap-3 lg:overflow-hidden lg:p-3">
      {isDesktop && (space === 'learn' ? <LearnSidebar /> : <Sidebar />)}
      <main
        className="min-w-0 flex-1 overflow-y-auto pb-20 lg:pb-0 lg:overflow-y-auto"
        style={
          !isDesktop
            ? { paddingBottom: 'calc(env(safe-area-inset-bottom, 0) + 5rem)' }
            : undefined
        }
      >
        {/* Suspense внутри Shell: при загрузке lazy-страницы layout не мигает. */}
        <Suspense fallback={<SkeletonRows rows={6} className="p-6" />}>
          <Outlet />
        </Suspense>
      </main>
      {!isDesktop && <MobileBottomTabBar space={space} />}
    </div>
  )
}
