import { cn } from '@/lib/cn'
import { type TaskPriority } from '@/lib/tasks'

/**
 * Приоритет — планка 3px у левого края, а не бейдж в потоке.
 *
 * 87% задач в проде — `medium`, и бейдж в каждой строке означал бы, что почти
 * каждая строка несёт слово, ничего не сообщающее. У `medium` планки нет
 * буквально: нода не рендерится, ноль занятой ширины. Прежний код рисовал
 * `high` и `urgent` одинаковым красным — шкалы из четырёх значений не было.
 *
 * Планка НЕ отвечает за выделение строки: у выбранной строки собственный
 * амбер-контур, и красная планка `urgent` перекрывала бы его, из-за чего
 * «выбрано» выглядело бы по-разному на разных приоритетах.
 */

const TONE: Record<TaskPriority, string | null> = {
  urgent: 'bg-red',
  high: 'bg-amber',
  low: 'bg-blue-deep',
  medium: null,
}

interface PriorityBarProps {
  priority: TaskPriority
  /** Вертикальные отступы от краёв контейнера: 9px в строке, 10px на карточке. */
  className?: string
}

export function PriorityBar({ priority, className }: PriorityBarProps) {
  const tone = TONE[priority]
  if (!tone) return null
  return (
    <span
      aria-hidden
      className={cn(
        'pointer-events-none absolute left-0 w-[3px] rounded-r-[3px]',
        tone,
        className ?? 'inset-y-[9px]',
      )}
    />
  )
}
