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
  'shift.new',
  'shift.application',
  'shift.result',
  'assessment.assigned',
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
  'shift.new': 'Новая смена на бирже (моя должность)',
  'shift.application': 'Отклик на мою смену (для руководителей)',
  'shift.result': 'Результат по смене (назначили/отменили)',
  'assessment.assigned': 'Назначена аттестация',
}

/**
 * Разделы страницы уведомлений. Карта ПОЛНАЯ по построению: тип
 * `Record<NotificationKind, ...>` не даст добавить вид без раздела, а тест
 * следит, что все 20 на месте.
 */
export type NotificationGroup = 'tasks' | 'learn' | 'shifts'

export const NOTIFICATION_GROUP_LABEL: Record<NotificationGroup, string> = {
  tasks: 'Задачи',
  learn: 'Обучение и библиотека',
  shifts: 'Смены и аттестация',
}

export const NOTIFICATION_GROUP_ORDER: NotificationGroup[] = [
  'tasks',
  'learn',
  'shifts',
]

export const KIND_GROUP: Record<NotificationKind, NotificationGroup> = {
  'task.assigned_to_me': 'tasks',
  'task.mentioned': 'tasks',
  'task.commented_on_watched': 'tasks',
  'task.status_changed_on_watched': 'tasks',
  'task.due_soon': 'tasks',
  'task.overdue': 'tasks',
  'library.ack_required': 'learn',
  'content.review_due': 'learn',
  'news.published': 'learn',
  'news.ack_required': 'learn',
  'survey.assigned': 'learn',
  'course.assigned': 'learn',
  'course.due_soon': 'learn',
  'quiz.review_needed': 'learn',
  'quiz.reviewed': 'learn',
  'profile.inactivity': 'shifts',
  'shift.new': 'shifts',
  'shift.application': 'shifts',
  'shift.result': 'shifts',
  'assessment.assigned': 'shifts',
}
