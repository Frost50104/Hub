import { api } from './api'
import { isVideoFile } from './attachmentTypes'

export interface Attachment {
  id: string
  task_id: string
  filename: string
  mime: string
  size_bytes: number
  uploaded_by: string
  created_at: string
  uploader_email: string | null
  uploader_full_name: string | null
  /**
   * Подписанный адрес файла — приходит ТОЛЬКО у видео.
   *
   * `null` значит и «не видео», и «бэкенд ещё не выкачен»: поле появилось
   * 15.09, и вкладка со старым бандлом на новом сервере, как и новый бандл на
   * старом сервере, обязаны работать без плеера, а не падать.
   */
  preview_url?: string | null
}

export const attachmentsApi = {
  list: (taskId: string): Promise<Attachment[]> =>
    api.get<Attachment[]>(`/tasks/${taskId}/attachments`).then((r) => r.data),

  /**
   * Загрузка идёт на ФИКСИРОВАННЫЙ адрес `/attachments`, а `task_id` едет
   * полем формы. Причина не в красоте: потолок размера тела задаёт nginx, а
   * локацию под прежний адрес с UUID внутри сделать нельзя — он живёт под
   * `location ^~ /api/`, а `^~` отменяет проверку regex-локаций. Подробности
   * — в докстринге ручки `app/api/attachments.py::upload_attachment`.
   *
   * `onProgress` обязателен по смыслу, хоть и необязателен по типу: гигабайт
   * по мобильному каналу идёт десятки минут, и без индикатора это выглядит как
   * зависшее приложение.
   */
  upload: (
    taskId: string,
    file: File,
    onProgress?: (fraction: number) => void,
  ): Promise<Attachment> => {
    const form = new FormData()
    form.append('task_id', taskId)
    form.append('file', file)
    return api
      .post<Attachment>('/attachments', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (event) => {
          if (!onProgress) return
          // `total` известен не всегда (например, при chunked-кодировании) —
          // тогда процента нет, и вызывающий покажет неопределённое состояние.
          if (!event.total) return
          onProgress(event.loaded / event.total)
        },
      })
      .then((r) => r.data)
  },

  /**
   * Скачивание.
   *
   * Обычные файлы тянем блобом: axios подставит Bearer, а `<a href>` этого не
   * умеет и сохранил бы тело ответа 401. Для ВИДЕО так делать нельзя — блоб
   * размером с гигабайт живёт в памяти вкладки, — поэтому у него есть
   * подписанный адрес, и переход по нему делается прямо в жесте клика.
   */
  download: async (attachment: Attachment): Promise<void> => {
    if (attachment.preview_url) {
      window.open(`${attachment.preview_url}&dl=1`, '_blank', 'noopener')
      return
    }
    const resp = await api.get(`/attachments/${attachment.id}/download`, {
      responseType: 'blob',
    })
    const url = URL.createObjectURL(resp.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = attachment.filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },

  remove: (attachmentId: string): Promise<void> =>
    api.delete(`/attachments/${attachmentId}`).then(() => undefined),
}

/** Показывать ли строку плеером: сервер дал адрес И это действительно видео. */
export function attachmentIsPlayable(attachment: Attachment): boolean {
  return Boolean(
    attachment.preview_url &&
      (attachment.mime.startsWith('video/') || isVideoFile(attachment.filename)),
  )
}

// Правила типов и размера живут в `attachmentTypes.ts` (без axios и DOM, под
// тестами); здесь — реэкспорт, чтобы прежние импорты продолжали работать.
export {
  ALLOWED_EXTENSIONS,
  ATTACHMENT_ACCEPT,
  ATTACHMENT_TYPES_HUMAN,
  ATTACHMENT_VIDEO_MAX_BYTES,
  attachmentSizeError,
  attachmentTypeError,
  fileExtension,
  formatBytes,
  isVideoFile,
} from './attachmentTypes'
