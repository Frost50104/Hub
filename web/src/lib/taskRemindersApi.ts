/**
 * HTTP-клиент личных напоминаний (0062). Отдельно от `lib/taskReminders.ts`:
 * тот чистый и живёт под vitest без jsdom, а этот тянет axios-клиент.
 */

import { api } from '@/lib/api'
import type { ReminderCreateBody, TaskRemindersResponse } from '@/lib/taskReminders'

export const taskRemindersApi = {
  list: (taskId: string): Promise<TaskRemindersResponse> =>
    api.get<TaskRemindersResponse>(`/tasks/${taskId}/reminders`).then((r) => r.data),
  create: (taskId: string, body: ReminderCreateBody): Promise<TaskRemindersResponse> =>
    api.post<TaskRemindersResponse>(`/tasks/${taskId}/reminders`, body).then((r) => r.data),
  remove: (taskId: string, reminderId: string): Promise<void> =>
    api.delete(`/tasks/${taskId}/reminders/${reminderId}`).then(() => undefined),
}
