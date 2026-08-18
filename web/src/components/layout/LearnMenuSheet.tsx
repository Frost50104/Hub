import { ChevronRight, User } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { ADMIN_NAV, LEARN_MENU_ITEMS } from './learnNav'
import { SpaceSwitcher } from './SpaceSwitcher'
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
    <BottomSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Меню"
      // Слот trailing у BottomSheet есть, но раньше не передавался — закрыть
      // лист можно было только тапом по оверлею.
      trailing={
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="-my-2.5 inline-flex min-h-[44px] items-center px-2 text-[15px] font-semibold text-text2 hover:text-text"
        >
          Готово
        </button>
      }
    >
      {/* Выход в «Задачи» с ЛЮБОГО learn-экрана: переключатель пространств
          на мобильном есть только в шапках витрин, а «Меню» доступно всегда.
          Без него из «Обучения» на телефоне было не выбраться.
          Закрываем по ВСПЛЫТИЮ, а не в capture: capture размонтирует лист
          раньше, чем отработает onClick самой кнопки, и навигация не
          происходила вовсе. */}
      <div className="px-3 pb-1" onClick={() => onOpenChange(false)}>
        <SpaceSwitcher />
      </div>
      <div className="mx-3 mb-1 h-px bg-hair" />

      {LEARN_MENU_ITEMS.map(({ to, label, icon: Icon, soon }) => (
        <BottomSheetItem
          key={to}
          icon={<Icon className="h-5 w-5" />}
          disabled={soon}
          onClick={() => go(to)}
          // Раздел ведёт на отдельный экран — шеврон об этом и говорит.
          trailing={<ChevronRight className="h-[18px] w-[18px]" />}
        >
          {label}
        </BottomSheetItem>
      ))}

      <div className="mx-3 my-1 h-px bg-hair" />
      <BottomSheetItem
        icon={<User className="h-5 w-5" />}
        onClick={() => go('/profile')}
        trailing={<ChevronRight className="h-[18px] w-[18px]" />}
      >
        Профиль
      </BottomSheetItem>

      {isAdmin && (
        <>
          <p className="px-3 pb-0.5 pt-2 text-[11px] font-bold uppercase tracking-[0.09em] text-text2">
            Управление
          </p>
          {ADMIN_NAV.map(({ to, label, icon: Icon }) => (
            <BottomSheetItem
              key={to}
              icon={<Icon className="h-5 w-5" />}
              onClick={() => go(to)}
              trailing={<ChevronRight className="h-[18px] w-[18px]" />}
            >
              {label}
            </BottomSheetItem>
          ))}
        </>
      )}
    </BottomSheet>
  )
}
