import { ThemeToggle } from '@/components/ThemeToggle'
import { useMe } from '@/hooks/useMe'
import { useIsDesktop } from '@/hooks/useMediaQuery'

export function AppearanceTab() {
  const isDesktop = useIsDesktop()
  const me = useMe()
  // Подпись обязана совпадать с реальностью: без серверной синхронизации
  // (старый бэкенд в окне деплоя) выбор действительно живёт в браузере.
  const synced = me.data?.theme !== undefined
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="font-display text-[17px] font-bold text-text">Тема оформления</h2>
        <p className="mt-1 text-[14px] text-text2">
          {synced
            ? 'Выбор привязан к вашей учётной записи и применяется на всех ваших устройствах.'
            : 'Выбор сохраняется в этом браузере.'}
        </p>
      </div>
      <ThemeToggle className="max-w-sm" size={isDesktop ? 'sm' : 'lg'} />
    </div>
  )
}
