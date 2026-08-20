import { ThemeToggle } from '@/components/ThemeToggle'
import { useIsDesktop } from '@/hooks/useMediaQuery'

export function AppearanceTab() {
  const isDesktop = useIsDesktop()
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="font-display text-[17px] font-bold text-text">Тема оформления</h2>
        <p className="mt-1 text-[14px] text-text2">Выбор сохраняется в этом браузере.</p>
      </div>
      <ThemeToggle className="max-w-sm" size={isDesktop ? 'sm' : 'lg'} />
    </div>
  )
}
