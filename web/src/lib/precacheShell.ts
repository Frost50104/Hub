/**
 * Чистка HTML-оболочки из прекеша Service Worker'а.
 *
 * Зачем (ОС владельца 22.09, Safari на десктопе): на «Главной» баннер
 * «Доступно обновление» возвращался после каждого «Обновить» и после
 * обычной перезагрузки, а в «Настройках» кнопка срабатывала. Ровно этот сбой
 * 21.09 уже чинили для iPhone — HTML убран из прекеша (`vite.config.ts`), —
 * но правка действует лишь там, где воркер уже новый. Воркер, собранный до
 * 21.09, держит `index.html` в прекеше, и маршрут `precacheAndRoute` с
 * `directoryIndex` отдаёт её на навигацию к `/`: старая оболочка, старый
 * бандл, баннер снова на месте. Глубокие адреса (`/settings/…`) в прекеш не
 * попадают и идут в сеть — отсюда «в настройках работает». В Safari новый
 * воркер к тому же не встаёт (там же 16.09 замерено: `registration.update()`
 * не резолвится вовсе), и старый живёт неопределённо долго.
 *
 * Код в старую оболочку не доставить, пока жив старый воркер. Точка опоры —
 * общий для страницы и воркера `CacheStorage`: удаляем запись HTML сами, и
 * старый воркер на `/` уходит в сеть. Это штатное поведение
 * `workbox-precaching` 7.4.1 (стоит в lockfile с 28.05, `sw.ts` не менялся с
 * первого коммита — у любого старого воркера тот же код):
 * `PrecacheStrategy._handle` при промахе зовёт `_handleFetch`, там
 * `fallbackToNetwork = true` по умолчанию, а «ремонт» кеша (`cachePut`) —
 * только при SRI `integrity` в манифесте, которого у нас нет. То есть
 * удалённая запись обратно не возвращается.
 *
 * У нынешнего воркера HTML в манифесте нет вовсе (`deploy.sh` роняет выкат,
 * если `index.html` туда вернётся), поэтому для него чистка — пустой проход.
 *
 * Регистрацию и состояние воркера не трогаем: от регистрации зависит push, а
 * активация ожидающего воркера отсюда перезагрузила бы соседние вкладки
 * (слушатель `controlling` внутри плагина). Страницу не перезагружаем — это
 * инвариант приложения.
 *
 * Отдельным модулем ради теста: vitest здесь без jsdom.
 */

/** Префикс имени кеша прекеша Workbox (`workbox-precache-v2-<scope>`). */
const PRECACHE_PREFIX = 'workbox-precache'

/** Запись прекеша — HTML-оболочка (`/`, `/index.html?__WB_REVISION__=…`)? */
export function isPrecachedShell(cacheName: string, url: string): boolean {
  if (!cacheName.startsWith(PRECACHE_PREFIX)) return false
  let pathname: string
  try {
    pathname = new URL(url).pathname
  } catch {
    return false
  }
  return pathname === '/' || pathname.endsWith('.html')
}

/** Ровно то, что нужно от `CacheStorage` — ради фейка в тесте. */
export type CacheStorageLike = Pick<CacheStorage, 'keys' | 'open'>

/**
 * Удалить HTML-оболочку из прекеша. Возвращает число удалённых записей.
 *
 * Никогда не бросает: нет Cache API (небезопасный контекст), приватное окно
 * Safari, сбой хранилища — всё это 0. Чистка не должна ронять ни старт
 * приложения, ни кнопку «Обновить», в которой стоит перед перезагрузкой.
 */
export async function purgePrecachedShell(
  storage: CacheStorageLike | undefined = typeof caches === 'undefined' ? undefined : caches,
): Promise<number> {
  if (!storage) return 0
  let removed = 0
  try {
    for (const name of await storage.keys()) {
      if (!name.startsWith(PRECACHE_PREFIX)) continue
      const cache = await storage.open(name)
      for (const request of await cache.keys()) {
        if (isPrecachedShell(name, request.url) && (await cache.delete(request))) {
          removed += 1
        }
      }
    }
  } catch {
    // Хранилище недоступно или сбоит — оставляем как есть: хуже, чем было,
    // не станет, а следующий старт попробует снова.
  }
  return removed
}
