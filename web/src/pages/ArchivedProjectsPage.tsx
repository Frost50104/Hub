import { Archive } from 'lucide-react'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { ProjectKeyChip } from '@/components/project/ProjectKeyChip'
import { EmptyState } from '@/components/ui/EmptyState'
import { ListRow } from '@/components/ui/ListRow'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useProjects } from '@/hooks/useProjects'
import { archivedProjects } from '@/lib/archivedProjects'
import { dataAgeLabel } from '@/lib/dates'
import { projectContext } from '@/lib/projectAbout'
import { type Project } from '@/lib/projects'
import { shortDate } from '@/lib/taskDates'

/**
 * «Архив» — единственный вход в архивные проекты.
 *
 * До этого экрана попасть в них можно было только по прямой ссылке из истории
 * браузера: сервер прячет их из всех списков, а бейдж «архив» на `/projects`
 * был недостижим — страница запрашивает список без флага.
 *
 * Плоский список: папки и перетаскивание архиву не нужны, а `ProjectRow` со
 * страницы проектов завёрнут в `useDraggable` и тянет за собой папки. Собран
 * на тех же общих примитивах, что и она.
 *
 * Возврат из архива живёт в самом проекте («О проекте» → «Настройки проекта» →
 * «Архив») — решение владельца: строка здесь только открывает проект.
 */
export function ArchivedProjectsPage() {
  const isDesktop = useIsDesktop()
  const navigate = useNavigate()
  // include_archived АДДИТИВЕН: ручка отдаёт живые И архивные вперемешку,
  // поэтому отбор — на клиенте (см. lib/archivedProjects.ts).
  const projects = useProjects(true)
  const rows = useMemo(() => archivedProjects(projects.data), [projects.data])

  const body = projects.isLoading ? (
    <SkeletonRows rows={4} />
  ) : projects.isError ? (
    <EmptyState
      tone="error"
      layout="card"
      title="Не удалось загрузить архив"
      text="Проверьте соединение и попробуйте ещё раз."
      meta={dataAgeLabel(projects.dataUpdatedAt)}
      cta="Повторить"
      onCta={() => void projects.refetch()}
    />
  ) : rows.length === 0 ? (
    <EmptyState
      layout="card"
      icon={<Archive className="h-6 w-6" />}
      title="В архиве пусто"
      text="Архивный проект прячется из списков, но остаётся целиком: задачи, история и вложения на месте. Убрать проект в архив можно в «О проекте» → «Настройки проекта»."
    />
  ) : (
    <div className="flex flex-col">
      {rows.map((project: Project) => (
        <ListRow
          key={project.id}
          lead={<ProjectKeyChip project={project} size="md" />}
          title={project.name}
          // Бейдж «архив» здесь не рисуем: на экране архива он у всех и ничего
          // не различает. Полезнее дата — когда именно убрали.
          context={
            <span className="min-w-0 truncate">
              {[
                project.archived_at ? `В архиве с ${shortDate(project.archived_at)}` : null,
                projectContext(project),
              ]
                .filter(Boolean)
                .join(' · ')}
            </span>
          }
          onClick={() => navigate(`/projects/${project.id}`)}
          ariaLabel={`Открыть проект ${project.name}`}
        />
      ))}
    </div>
  )

  if (!isDesktop) {
    return (
      <div className="flex flex-col pb-6">
        <MobilePageHeader title="Архив" className="pb-2" />
        <div className={rows.length === 0 || projects.isError ? 'px-4' : undefined}>{body}</div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-[960px] flex-col gap-[18px] px-6 pb-10 pt-7">
      <header className="min-w-0">
        <h1 className="font-display text-[24px] font-bold leading-[1.2] text-text">Архив</h1>
        <p className="mt-[5px] text-[15px] text-text2">
          Проекты, убранные из списков. Внутри всё цело — задачи, история и вложения.
        </p>
      </header>
      {body}
    </div>
  )
}
