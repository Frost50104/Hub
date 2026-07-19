import { api } from './api'

export interface Notification {
  id: number
  kind: string
  title: string
  body: string
  url: string | null
  payload: Record<string, unknown> | null
  is_read: boolean
  read_at: string | null
  created_at: string
}

export interface UnreadCount {
  count: number
}

export interface PushSubscribeBody {
  endpoint: string
  keys: { p256dh: string; auth: string }
  user_agent?: string
}

export interface KindPreference {
  push: boolean
  in_app: boolean
}

export type PreferencesMap = Record<string, KindPreference>

export interface NotificationPrefs {
  prefs: PreferencesMap
}

/**
 * Trigger kinds emitted by `app/services/notify.py` — keep in sync with
 * `NOTIFICATION_KINDS` in `app/services/notification_prefs.py`.
 * Order here drives display order on /settings/notifications.
 */
export const NOTIFICATION_KINDS = [
  'task.assigned_to_me',
  'task.mentioned',
  'task.commented_on_watched',
  'task.status_changed_on_watched',
  'task.due_soon',
  'task.overdue',
  'library.ack_required',
  'content.review_due',
  'news.published',
  'news.ack_required',
  'survey.assigned',
  'course.assigned',
  'course.due_soon',
  'quiz.review_needed',
  'quiz.reviewed',
  'profile.inactivity',
] as const

export type NotificationKind = (typeof NOTIFICATION_KINDS)[number]

export const NOTIFICATION_KIND_LABEL: Record<NotificationKind, string> = {
  'task.assigned_to_me': 'Назначили задачу',
  'task.mentioned': 'Упомянули @меня в комментарии',
  'task.commented_on_watched': 'Комментарий в задаче, за которой я слежу',
  'task.status_changed_on_watched': 'Статус задачи изменён',
  'task.due_soon': 'Дедлайн через 24 часа',
  'task.overdue': 'Задача просрочена',
  'library.ack_required': 'Требуется ознакомление с документом',
  'content.review_due': 'Пора проверить актуальность материала',
  'news.published': 'Новая новость компании',
  'news.ack_required': 'Новость с обязательным ознакомлением',
  'survey.assigned': 'Назначен опрос',
  'course.assigned': 'Назначен курс обучения',
  'course.due_soon': 'Скоро дедлайн курса',
  'quiz.review_needed': 'Тест ждёт проверки (для проверяющих)',
  'quiz.reviewed': 'Мой тест проверен',
  'profile.inactivity': 'Предупреждение о неактивности',
}

export const notificationsApi = {
  list: (
    opts: { unread_only?: boolean; limit?: number; before_id?: number } = {},
  ): Promise<Notification[]> =>
    api.get<Notification[]>('/notifications', { params: opts }).then((r) => r.data),
  unreadCount: (): Promise<UnreadCount> =>
    api.get<UnreadCount>('/notifications/unread-count').then((r) => r.data),
  markRead: (id: number): Promise<void> =>
    api.post(`/notifications/${id}/read`).then(() => undefined),
  markAllRead: (): Promise<void> =>
    api.post('/notifications/read-all').then(() => undefined),
  getPreferences: (): Promise<NotificationPrefs> =>
    api.get<NotificationPrefs>('/notifications/preferences').then((r) => r.data),
  setPreferences: (prefs: PreferencesMap): Promise<NotificationPrefs> =>
    api
      .put<NotificationPrefs>('/notifications/preferences', { prefs })
      .then((r) => r.data),
}

export const pushApi = {
  subscribe: (body: PushSubscribeBody): Promise<void> =>
    api.post('/push/subscribe', body).then(() => undefined),
  unsubscribe: (endpoint: string): Promise<void> =>
    api
      .delete('/push/subscribe', { params: { endpoint } })
      .then(() => undefined),
}
