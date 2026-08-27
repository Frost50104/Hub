/**
 * Фото сотрудника из auth — по детерминированному URL, без поля в API.
 *
 * Ручка `auth.signaris.ru/api/avatars/{employee_id}` публичная: обычный `<img>`
 * без `Authorization`, `200 image/webp` при наличии фото и `404` иначе (CSP
 * основных локаций домен разрешает — `ops/nginx/hub-security-headers.conf`).
 * Поэтому URL не приезжает ни в одной схеме бэкенда: он выводится из
 * `employee_id`, который и так есть в каждом объекте про человека, а отдельное
 * поле раздуло бы каждый ответ списка (у крупного проекта он и так мегабайты).
 *
 * Базу дублируем, а не берём из `lib/auth.ts`: тот модуль тянет SSO-клиент и
 * IndexedDB, а этот нужен в vitest без jsdom — та же причина, по которой
 * отдельным файлом живёт `taskAssignees.ts`.
 */
const AVATAR_BASE = 'https://auth.signaris.ru/api/avatars'

export function avatarUrl(employeeId: string | null | undefined): string | undefined {
  return employeeId ? `${AVATAR_BASE}/${employeeId}` : undefined
}
