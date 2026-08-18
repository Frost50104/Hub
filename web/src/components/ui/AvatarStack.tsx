import { Avatar } from '@/components/ui/Avatar'
import { cn } from '@/lib/cn'
import { type TaskAssigneeBrief } from '@/lib/tasks'

const SIZE_CLASS = {
  xs: 'h-5 w-5 text-[9px]',
  sm: 'h-6 w-6 text-[9px]',
  md: 'h-7 w-7 text-[10px]',
} as const

// Перекрытие пропорционально размеру: фиксированные -ml-2 на 20px-аватаре
// съедали обводку и инициалы сливались в кашу («ДФ»+«ПП» → «дфпп»).
const OVERLAP_CLASS = {
  xs: '-ml-1.5',
  sm: '-ml-2',
  md: '-ml-2',
} as const

export type AvatarStackSize = keyof typeof SIZE_CLASS

interface AvatarStackProps {
  people: TaskAssigneeBrief[]
  /** Сколько аватаров показать до схлопывания в «+K». */
  max?: number
  size?: AvatarStackSize
  className?: string
  /** Что рендерить при пустом списке (напр. пунктирный кружок «Не назначено»). */
  emptyPlaceholder?: React.ReactNode
}

function label(p: TaskAssigneeBrief): string {
  return p.full_name || p.email || p.employee_id
}

/**
 * Наложенные аватары исполнителей.
 *
 * Обводка — `ring-glass-border`, а не цвет фона: стек живёт на разных
 * подложках (glass-карточка, surface-строка, обычный bg) и в обеих темах,
 * подбирать ring под каждую пришлось бы вручную.
 *
 * Ширина не фиксируется — контейнер-обёртка обязан позволять расти
 * (`w-auto`), иначе стек обрежется по ширине одного аватара.
 */
export function AvatarStack({
  people,
  max = 3,
  size = 'sm',
  className,
  emptyPlaceholder,
}: AvatarStackProps) {
  if (people.length === 0) return <>{emptyPlaceholder ?? null}</>

  const shown = people.slice(0, max)
  const hidden = people.slice(max)

  return (
    <div
      className={cn('flex shrink-0 items-center', className)}
      // Общий список — на обёртке aria-label: собственный title у Avatar
      // перебил бы title обёртки (браузер показывает внутренний).
      aria-label={`Исполнители: ${people.map(label).join(', ')}`}
    >
      {shown.map((p, i) => (
        <Avatar
          key={p.employee_id}
          name={p.full_name}
          email={p.email}
          className={cn(
            SIZE_CLASS[size],
            'ring-1 ring-glass-border',
            i > 0 && OVERLAP_CLASS[size],
          )}
          // Первый аватар сверху — иначе стек «читается» справа налево.
          style={{ zIndex: shown.length - i }}
        />
      ))}
      {hidden.length > 0 && (
        <span
          className={cn(
            SIZE_CLASS[size],
            OVERLAP_CLASS[size],
            'inline-flex select-none items-center justify-center rounded-full bg-surface font-medium text-text3 ring-1 ring-glass-border',
          )}
          title={hidden.map(label).join(', ')}
        >
          +{hidden.length}
        </span>
      )}
    </div>
  )
}
