import { plural } from './typography'

/**
 * Текст подтверждения удаления задачи.
 *
 * Удаление необратимо и уносит с собой то, чего человек в карточке не видит:
 * подзадачи (FK `tasks.parent_task_id` — ondelete CASCADE), комментарии,
 * вложения и историю. Цену называем ДО нажатия, а не тостом после — корзины
 * у задач нет.
 */
export function describeTaskDeletion(subtaskCount: number): string {
  const tail = 'Комментарии, вложения и история исчезнут — восстановить будет нельзя.'
  if (subtaskCount === 0) return tail
  // Согласование по числу: «1 подзадача удалятся» читается как брак продукта.
  const verb = subtaskCount === 1 ? 'удалится' : 'удалятся'
  const count = plural(subtaskCount, 'подзадача', 'подзадачи', 'подзадач')
  return `${count} ${verb} вместе с ней. ${tail}`
}
