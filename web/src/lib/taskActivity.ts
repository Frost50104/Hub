/**
 * Строка ленты задачи по записи activity — чистая функция ради vitest
 * (jsdom в проекте нет, компонент протестировать нечем).
 *
 * Лента хранит ФАКТЫ, а не тексты: старые записи (`status_changed` с
 * системными статусами) продолжают читаться после смены модели 0044.
 */

/** Подписи СТАРЫХ статусов — только для чтения истории: новых записей с ними
 *  не появляется, но на проде их 68. */
const LEGACY_STATUS_LABEL: Record<string, string> = {
  todo: 'К выполнению',
  in_progress: 'В работе',
  in_review: 'На проверке',
  done: 'Готово',
}

/** Ровно то, что нужно для строки; структурно совместимо с `threads.Activity`.
 *  Свой тип, а не импорт: `threads` тянет api-клиент, и юнит-тест без jsdom
 *  падал бы на `window`. */
export interface ActivityLike {
  kind: string
  payload?: Record<string, unknown> | null
  actor_full_name?: string | null
  actor_email?: string | null
}

export function renderActivity(a: ActivityLike): string | null {
  const actor = a.actor_full_name || a.actor_email || 'Кто-то'
  const p = (a.payload ?? {}) as Record<string, unknown>
  switch (a.kind) {
    case 'created':
      return `${actor} создал задачу`
    case 'updated':
      return `${actor} обновил задачу`
    case 'done_changed':
      return p['done'] ? `${actor} выполнил задачу` : `${actor} вернул задачу в работу`
    case 'stage_changed': {
      // stage_to пуст — статус сняли (0046), задача ушла с доски.
      const to = p['stage_to'] ? String(p['stage_to']) : null
      return to ? `${actor} перенёс в «${to}»` : `${actor} убрал статус`
    }
    case 'status_changed': {
      // LEGACY: записи до 0044 (на проде их 68). Имя колонки в них есть не
      // всегда, зато есть системный статус — иначе строка ленты схлопнулась бы
      // в «перевёл в «»».
      const to = p['stage_to'] ? String(p['stage_to']) : null
      const legacy = p['new'] ? LEGACY_STATUS_LABEL[String(p['new'])] : undefined
      const label = to ?? legacy ?? null
      return label ? `${actor} перевёл в «${label}»` : `${actor} изменил статус`
    }
    case 'assigned': {
      // Новый формат (0034) несёт added/removed со снапшотом имён. Старые
      // записи в БД остаются на old/new — ветка ниже их и рендерит.
      const added = Array.isArray(p['added']) ? (p['added'] as string[]) : null
      const removed = Array.isArray(p['removed']) ? (p['removed'] as string[]) : null
      if (added || removed) {
        const addedNames = (p['added_names'] as string[] | undefined) ?? []
        const removedNames = (p['removed_names'] as string[] | undefined) ?? []
        const hasAdded = (added?.length ?? 0) > 0
        const hasRemoved = (removed?.length ?? 0) > 0
        if (hasAdded && hasRemoved) {
          return `${actor} изменил исполнителей: +${addedNames.join(', ')}, −${removedNames.join(', ')}`
        }
        if (hasAdded) {
          return addedNames.length === 1
            ? `${actor} назначил исполнителем ${addedNames[0]}`
            : `${actor} добавил исполнителей: ${addedNames.join(', ')}`
        }
        if (hasRemoved) {
          return removedNames.length === 1
            ? `${actor} снял исполнителя ${removedNames[0]}`
            : `${actor} снял исполнителей: ${removedNames.join(', ')}`
        }
        return `${actor} изменил исполнителей`
      }
      const isUnassign = !p['new']
      return isUnassign
        ? `${actor} снял исполнителя`
        : `${actor} назначил исполнителя`
    }
    case 'moved': {
      // Единственный след прежнего номера: задача переехала в другой проект и
      // перенумеровалась (`uq_tasks_project_seq`), так что ссылки «PLP-118» в
      // переписке больше на неё не указывают. Имя проекта — снапшот на момент
      // события, как и везде в ленте.
      const from = p['from_project'] ? String(p['from_project']) : null
      const key = p['from_key'] ? String(p['from_key']) : null
      if (!from) return `${actor} перенёс задачу в другой проект`
      return key
        ? `${actor} перенёс задачу из «${from}» — прежний номер ${key}`
        : `${actor} перенёс задачу из «${from}»`
    }
    case 'archived':
      return `${actor} архивировал`
    case 'unarchived':
      return `${actor} восстановил из архива`
    case 'watcher_added':
      // С payload — редактор подписал другого (02.09); без — сам (легаси и /me).
      return p['name']
        ? `${actor} подписал ${String(p['name'])} на задачу`
        : `${actor} подписался на задачу`
    case 'watcher_removed':
      return p['name']
        ? `${actor} снял ${String(p['name'])} с наблюдения`
        : `${actor} отписался от задачи`
    case 'attached':
      return `${actor} прикрепил файл «${String(p['filename'] ?? '—')}»`
    case 'unattached':
      return `${actor} удалил файл «${String(p['filename'] ?? '—')}»`
    case 'labeled':
      return `${actor} добавил метку «${String(p['name'] ?? '—')}»`
    case 'unlabeled':
      return `${actor} снял метку «${String(p['name'] ?? '—')}»`
    case 'recurrence_set':
      return `${actor} включил повтор: ${String(p['rule'] ?? '—')}`
    case 'recurrence_cleared':
      return `${actor} выключил повтор`
    case 'recurrence_spawned':
      // Копию создаёт система, но по действию человека — он и назван.
      return `${actor} выполнил задачу — создана следующая${p['seq'] ? ` №${String(p['seq'])}` : ''}`
    case 'recurrence_created':
      return `Создана по повтору${p['seq'] ? ` из задачи №${String(p['seq'])}` : ''}`
    case 'recurrence_stopped':
      return p['reason'] === 'project_archived'
        ? 'Повтор остановлен: проект в архиве'
        : 'Повтор остановлен: задача в архиве'
    case 'commented':
      // Rendered as the comment itself — skip the activity row.
      return null
    default:
      return `${actor}: ${a.kind}`
  }
}
