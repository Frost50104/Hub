import { Download, Paperclip, Trash2, Upload } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { useMe } from '@/hooks/useMe'
import {
  useAttachments,
  useDeleteAttachment,
  useUploadAttachment,
} from '@/hooks/useAttachments'
import {
  ATTACHMENT_ACCEPT,
  ATTACHMENT_VIDEO_MAX_BYTES,
  attachmentIsPlayable,
  attachmentsApi,
  attachmentSizeError,
  attachmentTypeError,
  formatBytes,
  type Attachment,
} from '@/lib/attachments'
import { DrawerSection } from '@/components/task/DrawerSection'
import { cn } from '@/lib/cn'

/**
 * Плеер видео-вложения.
 *
 * `preload="metadata"` — не «auto»: гигабайтный файл начал бы выкачиваться в
 * момент открытия карточки задачи, ещё до того как его кто-то попросил.
 * `playsinline` — иначе iOS уводит воспроизведение в системный полноэкранный
 * плеер, и изнутри карточки это выглядит как «приложение куда-то перебросило».
 *
 * `onError` обязателен: браузеры договорились не про все контейнеры (Chrome не
 * декодирует MOV), и без обработчика человек видит чёрный прямоугольник без
 * единого слова о том, что случилось и что делать.
 */
function AttachmentPlayer({ attachment }: { attachment: Attachment }) {
  const [failed, setFailed] = useState(false)

  if (failed) {
    return (
      <p className="px-2 pb-1.5 text-[12px] text-text2">
        Этот браузер не проигрывает такое видео — скачайте файл, чтобы посмотреть.
      </p>
    )
  }
  return (
    <video
      src={attachment.preview_url ?? undefined}
      controls
      playsInline
      preload="metadata"
      onError={() => setFailed(true)}
      className="max-h-[320px] w-full rounded-md bg-black"
    />
  )
}

function AttachmentRow({
  attachment,
  isMine,
  onDelete,
}: {
  attachment: Attachment
  isMine: boolean
  onDelete: () => void
}) {
  const playable = attachmentIsPlayable(attachment)
  return (
    <div className="rounded-md border border-glass-border">
      <div className="group flex items-center gap-3 px-2 py-1.5">
        <Paperclip className="h-3.5 w-3.5 shrink-0 text-text2" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-text">{attachment.filename}</p>
          <p className="text-[12px] text-text2">
            {formatBytes(attachment.size_bytes)} ·{' '}
            {attachment.uploader_full_name || attachment.uploader_email || '—'}
          </p>
        </div>
        <button
          type="button"
          onClick={async () => {
            try {
              await attachmentsApi.download(attachment)
            } catch (err) {
              toast.error('Не удалось скачать', {
                description: (err as Error).message,
              })
            }
          }}
          className="rounded p-1 text-text2 hover:bg-glass hover:text-text"
          title="Скачать"
          aria-label="Скачать"
        >
          <Download className="h-3.5 w-3.5" />
        </button>
        {isMine && (
          <button
            onClick={onDelete}
            className="rounded p-1 text-text2 opacity-0 transition-opacity hover:text-red group-hover:opacity-100"
            aria-label="Удалить"
            title="Удалить"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {playable && <AttachmentPlayer attachment={attachment} />}
    </div>
  )
}

interface TaskAttachmentsProps {
  taskId: string
  /** false → viewer: дропзоны нет (сервер требует owner/editor на POST). */
  canEdit?: boolean
}

export function TaskAttachments({ taskId, canEdit = true }: TaskAttachmentsProps) {
  const me = useMe()
  const list = useAttachments(taskId)
  const upload = useUploadAttachment(taskId)
  const del = useDeleteAttachment(taskId)
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  // Доля загруженного текущего файла. Гигабайт по мобильному каналу идёт
  // десятки минут — без индикатора это неотличимо от зависшего приложения.
  const [progress, setProgress] = useState<number | null>(null)

  const submitFile = async (file: File) => {
    // Тип и размер проверяем до запроса (accept обходится выбором «все
    // файлы») — иначе сервер ответит голым 415, а nginx на слишком большом
    // теле оборвёт загрузку 413-м вообще без текста, уже после ожидания.
    const problem = attachmentTypeError(file) ?? attachmentSizeError(file)
    if (problem) {
      toast.error(problem)
      return
    }
    try {
      await upload.mutateAsync({ file, onProgress: setProgress })
      toast.success(`«${file.name}» загружен`)
    } catch {
      // тост показывает глобальный onError мутаций
    } finally {
      setProgress(null)
    }
  }

  const onPick = () => inputRef.current?.click()

  const onDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    for (const f of files) await submitFile(f)
  }

  const meId = me.data?.employee_id
  const percent = progress === null ? null : Math.round(progress * 100)

  return (
    <DrawerSection title="Вложения" count={list.data?.length ?? null}>

      <div className="space-y-1">
        {list.data?.map((a) => (
          <AttachmentRow
            key={a.id}
            attachment={a}
            isMine={a.uploaded_by === meId}
            onDelete={() => {
              if (confirm(`Удалить «${a.filename}»?`)) {
                void del.mutateAsync(a.id)
              }
            }}
          />
        ))}
      </div>

      {canEdit && (
        <>
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={onPick}
            className={cn(
              'flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed py-3 text-xs transition-colors',
              dragOver
                ? 'border-amber bg-amber/10 text-amber'
                : 'border-glass-border text-text2 hover:border-amber/50 hover:text-text2',
            )}
          >
            <Upload className="h-3.5 w-3.5" />
            {upload.isPending
              ? percent === null
                ? 'Загружаем…'
                : `Загружаем… ${percent}%`
              : 'Перетащите файл или нажмите'}
            {!upload.isPending && (
              <span className="text-[12px] opacity-60">
                до 20 МБ, видео до {formatBytes(ATTACHMENT_VIDEO_MAX_BYTES)}
              </span>
            )}
          </div>
          <input
            ref={inputRef}
            type="file"
            accept={ATTACHMENT_ACCEPT}
            className="hidden"
            onChange={async (e) => {
              const files = Array.from(e.target.files ?? [])
              e.target.value = ''
              for (const f of files) await submitFile(f)
            }}
          />

          <Button variant="ghost" size="sm" className="sr-only" onClick={onPick}>
            Загрузить
          </Button>
        </>
      )}
    </DrawerSection>
  )
}
