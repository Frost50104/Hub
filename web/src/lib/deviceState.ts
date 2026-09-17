/**
 * Что на устройстве принадлежит вошедшему человеку — и снимается при выходе.
 *
 * До этого логаут был четырьмя независимыми `authClient.logout()`, и он не
 * оставлял после себя ничего, кроме чистого IndexedDB с токенами — на общем
 * устройстве следующий вошедший наследовал тему предыдущего, его свёрнутые
 * папки и настройки колонок по UUID чужих проектов (ОС 09.09).
 *
 * Правило: чистим то, что принадлежит ЧЕЛОВЕКУ, и не трогаем то, что
 * принадлежит УСТРОЙСТВУ или самому логину. Поэтому здесь явный список, а не
 * `localStorage.clear()`.
 */

/** Ключи вошедшего человека — снимаются при выходе. */
export const PER_USER_LOCAL_KEYS = [
  'hub-theme', // анти-FOUC кеш темы (lib/theme.ts)
  'hub-theme-owner', // тег владельца кеша (там же)
  'hub-space', // последнее пространство: задачи/обучение (lib/workspace.ts)
  'hub-view-config', // видимые кастом-поля и свёрнутые секции по UUID проектов
  'hub-project-folders', // свёрнутые папки (stores/projectFolders.ts)
  'hub:push-last-sync', // троттл переподписки (lib/pushRefresh.ts)
  'hub:push-owner', // чей push-endpoint на сервере (там же)
] as const

export const PER_USER_SESSION_KEYS = ['hub:push-prompt-dismissed'] as const

/**
 * Чего в списках НЕТ и почему:
 * - `hub:push-opted-in` — разрешение выдано УСТРОЙСТВУ, и оно должно пережить
 *   выход: иначе вернувшемуся пришлось бы включать уведомления заново. Сама
 *   привязка endpoint'а к человеку снимается ниже, на сервере.
 * - `hub:preload-reload-at` — гард от цикла перезагрузок при выкате нового
 *   бандла (lib/preloadRecovery.ts), к пользователю отношения не имеет.
 * - `sso_pkce_verifier` / `sso_return_path` и `sso_pkce:<state>` — служебные
 *   ключи auth-клиента; снести их значит сломать сам редирект логаута и
 *   следующий вход. С либы 0.12 их стало больше и они лежат в ДВУХ
 *   хранилищах: запись попытки `sso_pkce:<state>` пишется и в `sessionStorage`,
 *   и в `localStorage` — чтобы callback, открывшийся в другой вкладке, мог
 *   завершить обмен (в `sessionStorage` исходной вкладки он не заглянет). Срок
 *   у записи свой — сутки, и чистится она самим клиентом после обмена.
 *   Поэтому список остаётся ЯВНЫМ и поимённым: префиксная зачистка
 *   `sso_pkce*` или `localStorage.clear()` снесла бы живую попытку входа.
 * - токены — IndexedDB, их чистит `store.clear()` внутри `authClient.logout()`.
 */
export function clearDeviceState(): void {
  for (const key of PER_USER_LOCAL_KEYS) {
    try {
      localStorage.removeItem(key)
    } catch {
      // Приватное окно / заблокированное хранилище: чистить нечего, но и
      // ронять логаут из-за этого нельзя.
    }
  }
  for (const key of PER_USER_SESSION_KEYS) {
    try {
      sessionStorage.removeItem(key)
    } catch {
      // см. выше
    }
  }
}

