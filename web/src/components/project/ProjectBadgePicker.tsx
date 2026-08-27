import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { ProjectKeyChip } from '@/components/project/ProjectKeyChip'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { useSetProjectBadge, useUploadProjectBadge } from '@/hooks/useProjects'
import { cn } from '@/lib/cn'
import {
  BADGE_ACCEPT,
  PROJECT_EMOJI,
  normalizeProjectEmoji,
  projectBadgeFileError,
} from '@/lib/projectBadge'
import { type Project } from '@/lib/projects'

/**
 * Выбор значка: эмодзи из палитры, свой эмодзи или картинка.
 *
 * Применение мгновенное, без «Сохранить»: у значка своя ручка, и двухшаговый
 * коммит уже загруженного файла был бы фальшью. «Убрать значок» в футере — это
 * и есть возврат к буквам, отдельного режима «Буквы» не заводим.
 *
 * Кроп не делаем: значок живёт на 22–40px, где центральный `object-cover`
 * визуально неотличим от ручной рамки. Вместо кроппера — превью на трёх
 * размерах и честная подпись «обрежется по центру».
 */
export function ProjectBadgePicker({
  project,
  open,
  onOpenChange,
}: {
  project: Project
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const [custom, setCustom] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const setBadge = useSetProjectBadge(project.id)
  const upload = useUploadProjectBadge(project.id)

  useEffect(() => {
    if (open) setCustom('')
  }, [open])

  const busy = setBadge.isPending || upload.isPending
  const customEmoji = normalizeProjectEmoji(custom)
  const hasBadge = Boolean(project.badge_emoji || project.badge_url)

  const applyEmoji = (emoji: string | null) => {
    if (busy) return
    setBadge.mutate(emoji)
  }

  const submitFile = (file: File) => {
    // Тип и размер проверяем ДО запроса: иначе сервер ответит голым 415, а
    // человек так и не узнает, какие форматы годятся.
    const error = projectBadgeFileError(file)
    if (error) {
      toast.error(error)
      return
    }
    upload.mutate(file)
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={(v) => !busy && onOpenChange(v)}
      title="Значок проекта"
      description="Заменяет квадрат с буквами в шапке, в сайдбаре и в списках."
      desktopWidth={480}
      footer={
        <>
          <Button
            type="button"
            variant="secondary"
            onClick={() => applyEmoji(null)}
            disabled={busy || !hasBadge}
          >
            Убрать значок
          </Button>
          <Button type="button" onClick={() => onOpenChange(false)} disabled={busy}>
            Готово
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        {/* Превью на трёх размерах: проверка на месте, а не после закрытия. */}
        <div className="flex items-center gap-3 rounded-xl border border-hair bg-tint p-3">
          <ProjectKeyChip project={project} size="xl" />
          <ProjectKeyChip project={project} size="md" />
          <ProjectKeyChip project={project} size="sm" />
          <p className="m-0 text-sm text-text2">
            Так проект выглядит в шапке, в списках и в сайдбаре.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <p className="m-0 text-[12px] font-bold uppercase tracking-[0.09em] text-text2">
            Эмодзи
          </p>
          <div className="grid grid-cols-8 gap-1.5">
            {PROJECT_EMOJI.map((emoji) => (
              <button
                key={emoji}
                type="button"
                aria-label={`Значок ${emoji}`}
                aria-pressed={project.badge_emoji === emoji}
                disabled={busy}
                onClick={() => applyEmoji(emoji)}
                className={cn(
                  'flex h-11 items-center justify-center rounded-lg border text-[20px] leading-none transition-colors lg:h-10',
                  project.badge_emoji === emoji
                    ? 'border-amber/55 bg-amber/15'
                    : 'border-glass-border bg-glass hover:bg-surface',
                )}
              >
                {emoji}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-sm text-text2" htmlFor="custom-emoji">
            Или вставьте свой
          </label>
          <div className="flex gap-2">
            <Input
              id="custom-emoji"
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              placeholder="🍩"
              className="flex-1"
            />
            <Button
              type="button"
              variant="secondary"
              disabled={busy || !customEmoji}
              onClick={() => customEmoji && applyEmoji(customEmoji)}
            >
              {customEmoji ? `Поставить ${customEmoji}` : 'Поставить'}
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <p className="m-0 text-[12px] font-bold uppercase tracking-[0.09em] text-text2">
            Картинка
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragOver(false)
              const file = e.dataTransfer.files[0]
              if (file) submitFile(file)
            }}
            className={cn(
              'flex flex-col items-center gap-1 rounded-xl border border-dashed px-3 py-5 text-sm transition-colors',
              dragOver
                ? 'border-amber bg-amber/10 text-text'
                : 'border-glass-border text-text2 hover:bg-glass',
            )}
          >
            <span>{upload.isPending ? 'Загружаем…' : 'Перетащите файл или нажмите'}</span>
            <span className="text-[12px] text-text3">
              PNG, JPG или WebP до 512 КБ. Квадратная лучше: обрежется по центру.
            </span>
          </button>
          <input
            ref={fileRef}
            type="file"
            accept={BADGE_ACCEPT}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) submitFile(file)
              e.target.value = ''
            }}
          />
        </div>
      </div>
    </ResponsiveDialog>
  )
}
