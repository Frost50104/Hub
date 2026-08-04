import { User } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { ADMIN_NAV, LEARN_MENU_ITEMS } from './learnNav'
import { BottomSheet, BottomSheetItem } from '@/components/ui/BottomSheet'
import { useMe } from '@/hooks/useMe'

/**
 * Мобильное меню learn-пространства — sheet со всеми разделами, не влезшими
 * в нижний таб-бар (паттерн Airbnb «Menu»). Списки — из learnNav.ts, те же,
 * что в десктопном LearnSidebar. Профиль здесь, потому что в learn-таб-баре
 * его вкладку заменила кнопка «Меню».
 */
export function LearnMenuSheet({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const me = useMe()
  const isAdmin = me.data?.hub_role === 'admin'

  // Закрыть ДО навигации: exit-анимация sheet'а не дерётся со сменой роута.
  const go = (to: string) => {
    onOpenChange(false)
    navigate(to)
  }

  return (
    <BottomSheet open={open} onOpenChange={onOpenChange} title="Меню">
      {LEARN_MENU_ITEMS.map(({ to, label, icon: Icon, soon }) => (
        <BottomSheetItem
          key={to}
          icon={<Icon className="h-5 w-5" />}
          disabled={soon}
          onClick={() => go(to)}
        >
          {label}
        </BottomSheetItem>
      ))}

      <div className="my-1 border-t border-glass-border" />
      <BottomSheetItem icon={<User className="h-5 w-5" />} onClick={() => go('/profile')}>
        Профиль
      </BottomSheetItem>

      {isAdmin && (
        <>
          <p className="px-3 pb-0.5 pt-2 text-[11px] font-semibold uppercase tracking-wider text-text3">
            Управление
          </p>
          {ADMIN_NAV.map(({ to, label, icon: Icon }) => (
            <BottomSheetItem
              key={to}
              icon={<Icon className="h-5 w-5" />}
              onClick={() => go(to)}
            >
              {label}
            </BottomSheetItem>
          ))}
        </>
      )}
    </BottomSheet>
  )
}
