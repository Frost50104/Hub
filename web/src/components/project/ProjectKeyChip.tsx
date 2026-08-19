import { cn } from '@/lib/cn'
import { type Project } from '@/lib/projects'

/**
 * Плашка ключа проекта — два первых знака.
 *
 * Палитра нейтральная плюс амбер у избранного. Прежняя хеш-функция раздавала
 * шесть случайных цветов, и они конфликтовали с правилом системы: зелёный
 * означает «сделано», синий — информативное. Цвет проекта ничего из этого не
 * сообщает, поэтому цветом отмечено ровно одно — личное избранное.
 */
export function ProjectKeyChip({
  project,
  size = 'md',
  className,
}: {
  project: Pick<Project, 'key' | 'is_favorite'>
  /** sm — сайдбар (22px), md — карточка на «Главной» (36px), lg — шапка (40px). */
  size?: 'sm' | 'md' | 'lg'
  className?: string
}) {
  return (
    <span
      aria-hidden
      className={cn(
        'flex shrink-0 items-center justify-center font-display font-bold uppercase',
        size === 'sm' && 'h-[22px] w-[22px] rounded-md text-[12px]',
        size === 'md' && 'h-9 w-9 rounded-[9px] text-[13px] font-black',
        size === 'lg' && 'h-10 w-10 rounded-[10px] text-base',
        project.is_favorite
          ? 'bg-amber text-on-amber'
          : 'border border-hair bg-tint text-text',
        className,
      )}
    >
      {project.key.slice(0, 2)}
    </span>
  )
}

/** «26 задач · 4 закрыты» — счётчики приходят с сервера, поэтому честные. */
export function projectMeta(project: Project): string | null {
  if (project.task_count == null) return null
  const total = project.task_count
  const done = project.done_count ?? 0
  const word = total % 10 === 1 && total % 100 !== 11 ? 'задача' : total % 10 >= 2 && total % 10 <= 4 && (total % 100 < 12 || total % 100 > 14) ? 'задачи' : 'задач'
  if (total === 0) return 'Пока нет задач'
  return done > 0 ? `${total} ${word} · ${done} закрыто` : `${total} ${word}`
}
