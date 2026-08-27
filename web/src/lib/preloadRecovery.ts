/**
 * Самолечение при провале ленивой загрузки чанка.
 *
 * Каждый деплой (`deploy.sh` → rsync `--delete`) удаляет старые хэшированные
 * чанки, а PWA, открытая на вчерашнем бандле, продолжает их запрашивать —
 * особенно на iOS, который выселяет кеш сервис-воркера. Пропавший чанк = 404 →
 * `import()` падает → React lazy бросает при рендере → человек видит «Что-то
 * пошло не так» (ОС 27.08, staging, минута в минуту с выкатом).
 *
 * Vite при провале динамического импорта шлёт `vite:preloadError` — по нему
 * перезагружаем страницу: свежий index.html ссылается на живые чанки, и сбой
 * превращается в незаметный рефреш.
 *
 * Защита от цикла обязательна: если падает и НОВЫЙ бандл (реальный баг, не
 * протухший кеш), безусловный reload крутил бы страницу вечно и человек не
 * увидел бы даже экрана ошибки.
 */

const STAMP_KEY = 'hub:preload-reload-at'
/** Одна перезагрузка за окно: повторный провал — уже не протухший кеш. */
export const RELOAD_WINDOW_MS = 60_000

/** Чистое решение «перезагружаться ли» — под тестами. */
export function shouldReloadOnPreloadError(
  lastReloadAt: number | null,
  now: number,
): boolean {
  return lastReloadAt === null || now - lastReloadAt >= RELOAD_WINDOW_MS
}

/** Разбор отметки из sessionStorage: мусор = «не перезагружались». */
export function parseReloadStamp(raw: string | null): number | null {
  if (!raw) return null
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : null
}

export function installPreloadRecovery(): void {
  window.addEventListener('vite:preloadError', (event) => {
    let last: number | null = null
    try {
      last = parseReloadStamp(sessionStorage.getItem(STAMP_KEY))
    } catch {
      // Хранилище недоступно (приватный режим) — перезагрузимся без защиты:
      // sessionStorage переживает reload, но не новую вкладку, риск цикла мал.
    }
    if (!shouldReloadOnPreloadError(last, Date.now())) return
    try {
      sessionStorage.setItem(STAMP_KEY, String(Date.now()))
    } catch {
      // см. выше
    }
    // preventDefault убирает бросок ошибки в рендер — иначе экран сбоя успеет
    // мигнуть до перезагрузки.
    event.preventDefault()
    window.location.reload()
  })
}
