/**
 * Нужно ли подтвердить push-подписку при запуске приложения.
 *
 * Подписка на iOS — вещь недолговечная: её снимает переустановка PWA, долгий
 * простой, иногда обновление системы. У Hub она ставилась ОДИН раз кнопкой и
 * больше не подтверждалась, а узнать о её смерти было неоткуда:
 * `PushPermissionPrompt` показывается только при `permission === 'default'`,
 * то есть человеку с выданным разрешением и мёртвой подпиской экран молчал.
 *
 * Лечение — тихая переподписка при запуске (паттерн Signaris Desk). Она же
 * продлевает `last_seen_at`, на котором держится гейт свежести на сервере.
 * Решение вынесено сюда, потому что у него три условия и все три легко
 * перепутать местами в эффекте.
 */

/** Разрешение было выдано хотя бы раз — значит подписку восстанавливать МОЖНО. */
const OPTED_IN_KEY = 'hub:push-opted-in'
/** Когда подписку подтверждали в последний раз (мс). */
const LAST_SYNC_KEY = 'hub:push-last-sync'

/** Чаще раза в 12 часов дёргать сервер незачем: подписка не портится за час. */
export const PUSH_SYNC_INTERVAL_MS = 12 * 60 * 60 * 1000

export interface PushRefreshState {
  permission: NotificationPermission | 'unsupported'
  /** Отметка из localStorage: человек когда-то включал уведомления. */
  optedIn: boolean
  /** Когда подтверждали в прошлый раз; null — никогда. */
  lastSyncAt: number | null
  now: number
}

/**
 * Стоит ли сейчас подтверждать подписку.
 *
 * Три «нет», и каждое существенно:
 * - разрешения нет — подписаться всё равно нельзя, а `requestPermission()` без
 *   жеста человека браузеры игнорируют;
 * - человек выключал уведомления сам — тихо включать их обратно нельзя;
 * - подтверждали недавно — не бьём в сервер на каждой навигации.
 */
export function shouldSyncPush(state: PushRefreshState): boolean {
  if (state.permission !== 'granted') return false
  if (!state.optedIn) return false
  if (state.lastSyncAt !== null && state.now - state.lastSyncAt < PUSH_SYNC_INTERVAL_MS) {
    return false
  }
  return true
}

/** Безопасное чтение: в приватном окне localStorage может бросать. */
function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Приватное окно / заблокированное хранилище: переподписка просто
    // случится в следующий раз. Ронять из-за этого приложение нельзя.
  }
}

export function isOptedIn(): boolean {
  return read(OPTED_IN_KEY) === '1'
}

/** Человек включил уведомления — с этого момента подписку можно восстанавливать. */
export function markOptedIn(): void {
  write(OPTED_IN_KEY, '1')
  markSynced()
}

/** Человек выключил уведомления — молча возвращать их нельзя. */
export function markOptedOut(): void {
  try {
    localStorage.removeItem(OPTED_IN_KEY)
    localStorage.removeItem(LAST_SYNC_KEY)
  } catch {
    // см. write()
  }
}

/**
 * Разбор отметки времени из хранилища. Чистая — в отличие от самого доступа к
 * `localStorage`, которого в тестовой среде проекта нет (vitest без jsdom).
 */
export function parseSyncStamp(raw: string | null): number | null {
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export function lastSyncAt(): number | null {
  return parseSyncStamp(read(LAST_SYNC_KEY))
}

export function markSynced(now: number = Date.now()): void {
  write(LAST_SYNC_KEY, String(now))
}

/**
 * base64url публичного VAPID-ключа → байты для `pushManager.subscribe`.
 *
 * Живёт здесь, а не в `usePush`: ключ разбирают ДВА места — кнопка подписки и
 * тихая переподписка, и разъехаться им нельзя.
 */
export function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const out = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}
