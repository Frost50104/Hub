import type { Theme } from '@/lib/theme'

/**
 * Что делать с темой, когда пришёл ответ `/api/me`.
 *
 * Логика вынесена в чистую функцию не ради красоты: у неё три входа, каждый со
 * своим «пустым» значением, и перепутать их местами легко, а последствия
 * молчаливые (чужая тема на устройстве или тёмная тема, записанная на сервер
 * всем, кто её не выбирал). Тестов на React-хуки в проекте нет (vitest без
 * jsdom), а на чистую функцию — есть.
 *
 * Три состояния `serverTheme` — это КОНТРАКТ, а не небрежность типа:
 *   `undefined` — поля нет в ответе. Старый бэкенд в окне деплоя и dev-стенд с
 *                 фикстурой: синхронизации нет, работаем как раньше, per-device.
 *   `null`      — поле есть, выбор не сделан. Можно засеять локальным.
 *   'light'|'dark' — сервер решил, он и побеждает.
 */
export type ThemeSyncAction =
  | { kind: 'adopt'; theme: Theme }
  | { kind: 'seed'; theme: Theme }
  | { kind: 'none' }

export interface ThemeSyncInput {
  /** `/api/me.theme`: undefined — поля нет, null — выбора нет. */
  serverTheme: Theme | null | undefined
  /** Кеш устройства; null — ключа нет вовсе (человек тему не трогал). */
  localTheme: Theme | null
  /** Тег владельца кеша (employee_id); null — legacy-кеш до выката. */
  localOwner: string | null
  employeeId: string
  /** Что сейчас на экране. */
  currentTheme: Theme
}

export function decideThemeSync(i: ThemeSyncInput): ThemeSyncAction {
  if (i.serverTheme === undefined) return { kind: 'none' }

  if (i.serverTheme !== null) {
    // Уже покрашено И кеш помечен нами — трогать стор незачем.
    if (i.serverTheme === i.currentTheme && i.localOwner === i.employeeId) {
      return { kind: 'none' }
    }
    return { kind: 'adopt', theme: i.serverTheme }
  }

  // На сервере пусто: переносим выбор, сделанный до выката. Чужой кеш (тег
  // указывает на другого человека) не переносим — иначе на общем устройстве
  // тема A стала бы темой аккаунта B, то есть исходный баг переехал бы в БД.
  if (i.localTheme === null) return { kind: 'none' }
  if (i.localOwner !== null && i.localOwner !== i.employeeId) return { kind: 'none' }
  return { kind: 'seed', theme: i.localTheme }
}
