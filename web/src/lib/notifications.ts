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

// Справочник видов и разделов вынесен в отдельный модуль без импорта `api`:
// иначе юнит-тест на полноту карты тянул бы auth-клиент и падал на `window`.
export {
  KIND_GROUP,
  NOTIFICATION_GROUP_LABEL,
  NOTIFICATION_GROUP_ORDER,
  NOTIFICATION_KINDS,
  NOTIFICATION_KIND_LABEL,
} from './notificationKinds'
export type { NotificationGroup, NotificationKind } from './notificationKinds'

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
