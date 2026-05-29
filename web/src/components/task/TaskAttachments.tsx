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
import { attachmentsApi, formatBytes, type Attachment } from '@/lib/attachments'
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
      <Paperclip className="h-3.5 w-3.5 shrink-0 text-text3" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-text">{attachment.filename}</p>
        <p className="text-[10px] text-text3">
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
        className="rounded p-1 text-text3 hover:bg-glass hover:text-text"
        title="Скачать"
        aria-label="Скачать"
      >
        <Download className="h-3.5 w-3.5" />
      </button>
      {isMine && (
        <button
          onClick={onDelete}
          className="rounded p-1 text-text3 opacity-0 transition-opacity hover:text-red group-hover:opacity-100"
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
}

export function TaskAttachments({ taskId }: TaskAttachmentsProps) {
  const me = useMe()
  const list = useAttachments(taskId)
  const upload = useUploadAttachment(taskId)
  const del = useDeleteAttachment(taskId)
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const submitFile = async (file: File) => {
    if (file.size > MAX_BYTES) {
      toast.error(`«${file.name}» больше 20 МБ — не загрузится`)
      return
    }
    try {
      await upload.mutateAsync(file)
      toast.success(`«${file.name}» загружен`)
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
        (err as Error).message
      toast.error('Не удалось загрузить', { description: detail })
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
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-text3">
        Вложения {list.data ? `(${list.data.length})` : ''}
      </h3>

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
            : 'border-glass-border text-text3 hover:border-amber/50 hover:text-text2',
        )}
      >
        <Upload className="h-3.5 w-3.5" />
        {upload.isPending ? 'Загружаем…' : 'Перетащите файл или нажмите'}
        <span className="text-[10px] opacity-60">до 20 МБ</span>
      </div>
      <input
        ref={inputRef}
        type="file"
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
    </section>
  )
}
