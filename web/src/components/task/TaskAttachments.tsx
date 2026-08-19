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
  attachmentsApi,
  attachmentTypeError,
  formatBytes,
  type Attachment,
} from '@/lib/attachments'
import { DrawerSection } from '@/components/task/DrawerSection'
import { cn } from '@/lib/cn'

const MAX_BYTES = 20 * 1024 * 1024

function AttachmentRow({
  attachment,
  isMine,
  onDelete,
}: {
  attachment: Attachment
  isMine: boolean
  onDelete: () => void
}) {
  return (
    <div className="group flex items-center gap-3 rounded-md border border-glass-border px-2 py-1.5">
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
            await attachmentsApi.download(attachment.id, attachment.filename)
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

  const submitFile = async (file: File) => {
    // Тип проверяем до запроса (accept обходится выбором «все файлы») —
    // иначе сервер ответит голым 415 без списка допустимого.
    const typeError = attachmentTypeError(file)
    if (typeError) {
      toast.error(typeError)
      return
    }
    if (file.size > MAX_BYTES) {
      toast.error(`«${file.name}» больше 20 МБ — не загрузится`)
      return
    }
    try {
      await upload.mutateAsync(file)
      toast.success(`«${file.name}» загружен`)
    } catch {
      // тост показывает глобальный onError мутаций
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
            {upload.isPending ? 'Загружаем…' : 'Перетащите файл или нажмите'}
            <span className="text-[12px] opacity-60">до 20 МБ</span>
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
