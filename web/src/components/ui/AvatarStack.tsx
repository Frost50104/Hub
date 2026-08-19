import { Avatar } from '@/components/ui/Avatar'
import { cn } from '@/lib/cn'
import { type TaskAssigneeBrief } from '@/lib/tasks'

// Шкала редизайна: минимум 12px даже в 24px-круге — два знака bold занимают
// 17px и влезают с запасом, а прежние 9-10px были тем же дефектом старой
// шкалы трекера.
const SIZE_CLASS = {
  xs: 'h-5 w-5 text-[12px]',
  sm: 'h-6 w-6 text-[12px]',
  md: 'h-7 w-7 text-[13px]',
} as const

// −4px, а не −8: видимая полоса должна быть шире двухбуквенного глифа, иначе
// непрозрачный сосед срезает вторую букву и «ДФ» не отличить от «ДС».
const OVERLAP = '-ml-1'

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
 * Обводка выводится из КРАСКИ (`--text2`), а не из подложки: заливка --av-fill
 * близка к цвету страницы, поэтому ring в цвет страницы совпадал с заливкой
 * соседа и границы не было. `--text2` против той же заливки даёт 4,6:1 в
 * тёмной и ~6:1 в светлой — перекрытие читается.
 *
 * «+N» получает нейтральную обводку `--glass-border`, чтобы счётчик не
 * выглядел ещё одним человеком.
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
            'ring-[1.5px] ring-text2',
            i > 0 && OVERLAP,
          )}
          // Первый аватар сверху — иначе стек «читается» справа налево.
          style={{ zIndex: shown.length - i }}
        />
      ))}
      {hidden.length > 0 && (
        <span
          className={cn(
            SIZE_CLASS[size],
            OVERLAP,
            'inline-flex select-none items-center justify-center rounded-full bg-av-fill font-bold text-text ring-[1.5px] ring-glass-border',
          )}
          title={hidden.map(label).join(', ')}
        >
          +{hidden.length}
        </span>
      )}
    </div>
  )
}
