import { api } from './api'

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
}

export const attachmentsApi = {
  list: (taskId: string): Promise<Attachment[]> =>
    api.get<Attachment[]>(`/tasks/${taskId}/attachments`).then((r) => r.data),
  upload: (taskId: string, file: File): Promise<Attachment> => {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<Attachment>(`/tasks/${taskId}/attachments`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },
  /**
   * Fetch the file as a blob (carries Bearer token via axios) and trigger
   * a download via a synthetic <a download>. A bare `<a href>` won't add
   * Authorization headers, so the browser would save the 401 response body
   * instead of the actual file.
   */
  download: async (attachmentId: string, filename: string): Promise<void> => {
    const resp = await api.get(`/attachments/${attachmentId}/download`, {
      responseType: 'blob',
    })
    const url = URL.createObjectURL(resp.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },
  remove: (attachmentId: string): Promise<void> =>
    api.delete(`/attachments/${attachmentId}`).then(() => undefined),
}

// Правила типов и размера живут в `attachmentTypes.ts` (без axios и DOM, под
// тестами); здесь — реэкспорт, чтобы прежние импорты продолжали работать.
export {
  ALLOWED_EXTENSIONS,
  ATTACHMENT_ACCEPT,
  ATTACHMENT_TYPES_HUMAN,
  attachmentTypeError,
  fileExtension,
  formatBytes,
} from './attachmentTypes'
