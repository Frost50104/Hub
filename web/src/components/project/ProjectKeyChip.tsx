import { useState } from 'react'

import { cn } from '@/lib/cn'
import { type Project } from '@/lib/projects'
import { type ProjectBadgeSource, resolveProjectBadge } from '@/lib/projectBadge'

/**
 * Бейдж проекта: картинка, эмодзи или две буквы ключа — в этом порядке.
 *
 * Палитра букв нейтральная плюс амбер у избранного. Прежняя хеш-функция
 * раздавала шесть случайных цветов, и они конфликтовали с правилом системы:
 * зелёный означает «сделано», синий — информативное. Цвет проекта ничего из
 * этого не сообщает, поэтому цветом отмечено ровно одно — личное избранное.
 *
 * ЕДИНСТВЕННЫЙ рисователь квадрата. Шапка проекта раньше держала свою копию с
 * захардкоженным амбером — то есть сообщала «избранное» всем подряд.
 *
 * Probe-стора, как у `Avatar`, здесь нет намеренно: там адрес ВЫВОДИТСЯ из
 * employee_id и сервер про наличие фото молчит, а тут `badge_url === null`
 * прямо означает «картинки нет» — лишний `<img>` не создаётся вовсе. Плюс
 * порядок величин другой: проектов десятки, а не тысячи строк списка задач.
 * Поэтому обычного `onError` с откатом на буквы достаточно.
 */
export function ProjectKeyChip({
  project,
  size = 'md',
  className,
}: {
  project: ProjectBadgeSource
  /** sm — сайдбар (22px), md — списки (36px), lg — шапка (40px), xl — превью (64px). */
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
}) {
  const [broken, setBroken] = useState(false)
  const badge = resolveProjectBadge(project)
  const kind = badge.kind === 'image' && broken ? 'letters' : badge.kind

  const box = cn(
    'flex shrink-0 items-center justify-center overflow-hidden font-display font-bold uppercase',
    size === 'sm' && 'h-[22px] w-[22px] rounded-md text-[12px]',
    size === 'md' && 'h-9 w-9 rounded-[9px] text-[13px] font-black',
    size === 'lg' && 'h-10 w-10 rounded-[10px] text-base',
    size === 'xl' && 'h-16 w-16 rounded-[14px] text-2xl',
    // Под картинкой заливки не видно, поэтому избранное там — кольцо. Без
    // этого признак молча исчезал бы у проектов со значком.
    kind === 'letters'
      ? project.is_favorite
        ? 'bg-amber text-on-amber'
        : 'border border-hair bg-tint text-text'
      : cn('border border-hair bg-tint', project.is_favorite && 'ring-1 ring-amber'),
    className,
  )

  if (kind === 'image' && badge.kind === 'image') {
    return (
      <span aria-hidden className={box}>
        <img
          src={badge.url}
          alt=""
          loading="lazy"
          decoding="async"
          className="h-full w-full object-cover"
          onError={() => setBroken(true)}
        />
      </span>
    )
  }

  if (kind === 'emoji' && badge.kind === 'emoji') {
    return (
      <span aria-hidden className={box}>
        {/* leading-none обязателен: эмодзи наследует line-height и в
            22-пиксельном квадрате садится ниже центра. */}
        <span
          className={cn(
            'leading-none',
            size === 'sm' && 'text-[13px]',
            size === 'md' && 'text-[20px]',
            size === 'lg' && 'text-[22px]',
            size === 'xl' && 'text-[38px]',
          )}
        >
          {badge.emoji}
        </span>
      </span>
    )
  }

  return (
    <span aria-hidden className={box}>
      {badge.kind === 'letters' ? badge.letters : project.key.slice(0, 2).toUpperCase()}
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
  return done > 0 ? `${total} ${word} · ${done} закрыто` : `${total} ${word}`
}
