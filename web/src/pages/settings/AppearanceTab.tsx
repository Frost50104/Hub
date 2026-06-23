import { ThemeToggle } from '@/components/ThemeToggle'

export function AppearanceTab() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-text">Тема оформления</h2>
        <p className="mt-1 text-xs text-text2">
          Выбор сохраняется в этом браузере.
        </p>
      </div>
      <ThemeToggle className="max-w-sm" />
    </div>
  )
}
