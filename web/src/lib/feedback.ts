import { api } from './api'

export {
  addFeedbackFiles,
  FEEDBACK_ACCEPT,
  FEEDBACK_FILES_MAX,
  FEEDBACK_TEXT_MAX,
  FEEDBACK_TOTAL_MAX,
  feedbackFileError,
  feedbackFilesSize,
  type FeedbackFilesResult,
} from './feedbackFiles'

export const feedbackApi = {
  send: (text: string, files: readonly File[] = []): Promise<void> => {
    const form = new FormData()
    form.append('text', text)
    // Поле называется `files` и повторяется — так FastAPI собирает список.
    for (const file of files) form.append('files', file)
    return api
      .post('/feedback', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then(() => undefined)
  },
}
