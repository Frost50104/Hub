import { MoreHorizontal } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/Button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { useDeleteFolder } from '@/hooks/useProjects'
import { cn } from '@/lib/cn'
import { folderDeleteWarning } from '@/lib/folderActions'
import { type ProjectFolder } from '@/lib/projectFolders'

/**
 * «…» у папки проектов — общее для `/projects` и сайдбара.
 *
 * Вёрстка строки у двух поверхностей разная (там 13/700 и `min-h-8`, тут
 * 12/600 в колонке 260px), поэтому переиспользуется МЕНЮ, а не заголовок.
 * Переименование остаётся у вызывающего: инпут встраивается в его разметку.
 *
 * «Выше»/«Ниже» — опциональные: в сайдбаре порядок папок не меняют.
 */
export function FolderActionsMenu({
  folder,
  projectCount,
  onRenameStart,
  onMoveUp,
  onMoveDown,
  size = 'md',
  triggerClassName,
}: {
  folder: ProjectFolder
  projectCount: number
  onRenameStart: () => void
  onMoveUp?: () => void
  onMoveDown?: () => void
  /** xs — сайдбар (20px), md — десктоп (32px), lg — тач (44px). */
  size?: 'xs' | 'md' | 'lg'
  triggerClassName?: string
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const remove = useDeleteFolder()

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className={cn(
              'flex shrink-0 items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
              size === 'xs' && 'h-5 w-5',
              size === 'md' && 'h-8 w-8',
              size === 'lg' && 'h-11 w-11',
              triggerClassName,
            )}
            aria-label={`Действия с папкой «${folder.name}»`}
          >
            <MoreHorizontal className={size === 'xs' ? 'h-3.5 w-3.5' : 'h-4 w-4'} />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onSelect={() => {
              // Radix возвращает фокус на триггер после закрытия — без
              // отложенного монтирования autoFocus у инпута не сработает.
              // Держим отсрочку ЗДЕСЬ: у вызывающего её забыли бы.
              setTimeout(onRenameStart, 0)
            }}
          >
            Переименовать
          </DropdownMenuItem>
          {onMoveUp && <DropdownMenuItem onSelect={onMoveUp}>Выше</DropdownMenuItem>}
          {onMoveDown && <DropdownMenuItem onSelect={onMoveDown}>Ниже</DropdownMenuItem>}
          <DropdownMenuSeparator />
          <DropdownMenuItem destructive onSelect={() => setConfirmDelete(true)}>
            Удалить папку
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <ResponsiveDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={`Удалить папку «${folder.name}»?`}
        description={folderDeleteWarning(projectCount)}
        desktopWidth={440}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                remove.mutate(folder.id)
                setConfirmDelete(false)
              }}
            >
              Удалить
            </Button>
          </>
        }
      >
        <p className="m-0 text-sm text-text2">
          Сама папка — только раскладка: удаление не трогает ни проекты, ни их задачи.
        </p>
      </ResponsiveDialog>
    </>
  )
}
