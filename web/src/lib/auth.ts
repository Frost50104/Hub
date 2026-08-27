import {
  createSsoAuthClient,
  type SsoAuthClient,
  type TokenSet,
  type TokenStore,
} from '@signaris/auth-client/browser'

const DB_NAME = 'signaris-hub-auth'
const DB_VERSION = 1
const STORE_NAME = 'tokens'
const KEY = 'main'

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onerror = () => reject(req.error)
    req.onsuccess = () => resolve(req.result)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME)
      }
    }
  })
}

async function dbGet(): Promise<TokenSet | null> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly')
    const req = tx.objectStore(STORE_NAME).get(KEY)
    req.onerror = () => reject(req.error)
    req.onsuccess = () => resolve((req.result as TokenSet | undefined) ?? null)
  })
}

async function dbPut(set: TokenSet | null): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    if (set === null) store.delete(KEY)
    else store.put(set, KEY)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

const indexedDBTokenStore: TokenStore = {
  async getAccessToken() {
    const t = await dbGet()
    return t?.access ?? null
  },
  async getRefreshToken() {
    const t = await dbGet()
    return t?.refresh ?? null
  },
  async save(t: TokenSet) {
    await dbPut(t)
  },
  async clear() {
    await dbPut(null)
  },
}

// PWA standalone (iOS) has its own cookie jar, so we use IndexedDB tokens
// and `X-Auth-Mode: api` (set in lib/api.ts). For regular browsers this also
// works fine — refresh-token in IDB beats localStorage on the XSS surface.
/**
 * Адрес auth — ОДНА константа на весь фронт.
 *
 * Кроме SSO-клиента к ней ходят настройки: «Редактировать профиль» ведёт на
 * `/me` (имя, аватар, 2FA, пароль). Второй хардкод домена рано или поздно
 * разъедется с этим.
 */
export const AUTH_BASE_URL = 'https://auth.signaris.ru'

/** Страница профиля сотрудника в auth. */
export const AUTH_PROFILE_URL = `${AUTH_BASE_URL}/me`

export const authClient: SsoAuthClient = createSsoAuthClient({
  authBaseUrl: AUTH_BASE_URL,
  redirectUri: `${window.location.origin}/auth/callback`,
  store: indexedDBTokenStore,
  logoutReturnTo: `${window.location.origin}/login`,
})
