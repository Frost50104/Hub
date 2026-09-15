import { Link } from 'react-router-dom'

import { chipVariants } from '@/components/ui/Chip'
import { cn } from '@/lib/cn'
import { type TaskProjectLabel } from '@/lib/taskProjectLabel'

/**
 * Чип проекта в строке задачи — ссылка на страницу проекта (16.09).
 *
 * Владелец: «имя проекта под заголовком выглядит как простой текст, а
 * колонка — как чип; должно быть наоборот, и при нажатии на чип должен
 * открываться сам проект». Силуэт — `Chip` (22px, 12/600): имя проекта вводит
 * пользователь, значит это значение, а не статус.
 *
 * Строка списка вокруг чипа — `<div role="button">` со своими `onClick` и
 * `onKeyDown` (Enter/Space → `preventDefault` + открыть карточку). Отсюда три
 * `stopPropagation`: без первого клик по чипу открывал бы ещё и карточку, без
 * `onKeyDown` Enter на сфокусированной ссылке отменялся бы строкой и открывал
 * карточку вместо проекта. `preventDefault` НЕ зовём — `Link` переходит,
 * только если событие не отменено. Прецедент — `TaskDoneControl`.
 *
 * `to === null` — чип без ссылки: подпись-фолбэк из ключа проекта значит, что
 * меня в проекте нет, и страница ответила бы 404 (см. `taskProjectLabel`).
 *
 * Многоточие: `truncate` на самом `inline-flex` не работает — обрезается
 * вложенный `span` с `min-w-0` (урок `TaskListHeader`).
 */
export function ProjectChip({
  label,
  className,
}: {
  label: TaskProjectLabel | null | undefined
  className?: string
}) {
  const text = label?.text
  if (!label || !text) return null
  if (!label.to) {
    return (
      <span
        className={cn(
          chipVariants({ variant: 'neutral', size: 'sm' }),
          'min-w-0 overflow-hidden',
          className,
        )}
        title={`Проект: ${text}`}
      >
        <span className="min-w-0 truncate">{text}</span>
      </span>
    )
  }
  return (
    <Link
      to={label.to}
      title={`Открыть проект «${text}»`}
      onClick={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      className={cn(
        chipVariants({ variant: 'neutral', size: 'sm' }),
        'min-w-0 overflow-hidden transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
        className,
      )}
    >
      <span className="min-w-0 truncate">{text}</span>
    </Link>
  )
}
