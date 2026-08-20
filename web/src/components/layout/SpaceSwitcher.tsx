import { CheckSquare, GraduationCap } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'

import { cn } from '@/lib/cn'
import { useResolvedSpace, useWorkspace, type Space } from '@/lib/workspace'

const SPACES: { key: Space; label: string; icon: typeof CheckSquare; to: string }[] = [
  { key: 'tasks', label: 'Задачи', icon: CheckSquare, to: '/' },
  { key: 'learn', label: 'Обучение', icon: GraduationCap, to: '/learn' },
]

/**
 * Переключатель пространств «Задачи | Обучение» (segmented control).
 * Активное пространство выводится из URL; клик — навигация в корень
 * пространства + запоминание выбора для будущих сессий.
 *
 * Активный сегмент — нейтральный: рамка `--text2` и краска `--text`, без
 * амбера. `text-amber` на композите surface+bg-alt/60 давал в светлой теме
 * 1,65:1 — тот же дефект, что амбер-на-амбере в бейджах. Переключение
 * пространства — навигация «раз в день», амбер остаётся единственным акцентом
 * сайдбара — у кнопки создания. `size='lg'` — 44px для мобильной шапки и шторки.
 */
export function SpaceSwitcher({
  className,
  size = 'sm',
}: {
  className?: string
  size?: 'sm' | 'lg'
}) {
  const location = useLocation()
  const navigate = useNavigate()
  const rememberSpace = useWorkspace((s) => s.rememberSpace)
  // Резолвер, а не spaceFromPath: на нейтральных роутах (/inbox, /settings/*)
  // подсвечивается унаследованное пространство, а не «Задачи».
  const active = useResolvedSpace()

  return (
    <div
      role="tablist"
      aria-label="Пространство"
      className={cn(
        'flex rounded-lg border border-glass-border bg-bg-alt/60 p-0.5',
        className,
      )}
    >
      {SPACES.map(({ key, label, icon: Icon, to }) => (
        <button
          key={key}
          role="tab"
          aria-selected={active === key}
          onClick={() => {
            // Гейт по pathname, не по active: на нейтральном роуте (/inbox при
            // lastSpace='learn') сегмент «Обучение» уже active, но клик по нему
            // обязан вести на витрину, а не быть no-op'ом.
            if (location.pathname !== to) {
              rememberSpace(key)
              navigate(to)
            }
          }}
          className={cn(
            'flex flex-1 items-center justify-center gap-1.5 rounded-md border px-2 font-semibold transition-colors',
            size === 'lg' ? 'min-h-11 text-[14px]' : 'min-h-[30px] text-[12px]',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
            active === key
              ? 'border-text2 bg-transparent text-text'
              : 'border-transparent text-text2 hover:text-text',
          )}
        >
          <Icon className={size === 'lg' ? 'h-4 w-4' : 'h-3.5 w-3.5'} />
          {label}
        </button>
      ))}
    </div>
  )
}
