import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { shouldOfferUpdate } from '@/lib/appVersion'
import { TIMEOUT, withTimeout } from '@/lib/withTimeout'

/** Сколько ждём, пока найденное обновление доустановится до `waiting`. */
const INSTALL_TIMEOUT_MS = 20_000
/** Сколько ждём смены контроллера после SKIP_WAITING, прежде чем перезагрузить силой. */
const CONTROLLER_TIMEOUT_MS = 3_000
/**
 * Потолок ожидания `registration.update()`.
 *
 * Обязателен, и это измерено, а не предположено (ОС 16.09, Safari на
 * десктопе): `update()` там не резолвится ВООБЩЕ — замер в консоли живой
 * вкладки дал 15 002 мс без ответа и без отказа. Это был единственный `await`
 * во всём пути без ограничения по времени, поэтому кнопка оставалась
 * крутиться навсегда: ни тоста, ни перезагрузки. В Chrome тот же путь
 * отрабатывает за 1,6 с.
 */
const UPDATE_TIMEOUT_MS = 8_000

export type AppUpdateStatus = 'idle' | 'checking' | 'applying'

/**
 * Ручное обновление приложения.
 *
 * Зачем, если есть UpdateBanner: баннер показывается, только когда новый SW
 * УЖЕ доустановился и ждёт, а пользователь мог его пропустить, закрыть
 * «Позже» или сидеть в PWA, где iOS замораживает фоновые таймеры. В итоге
 * телефон неделями работает на старом бандле, и любая проверка правок
 * упирается в «а у тебя точно свежая версия?». Это ручной путь, доступный
 * всегда.
 *
 * Работаем на штатных SW-API, а НЕ на втором экземпляре `useRegisterSW`:
 * второй инстанс хука завёл бы собственную регистрацию и второй набор
 * колбэков рядом с UpdateBanner. `SKIP_WAITING` умеет обрабатывать наш
 * `src/sw.ts` — он же используется баннером.
 */
export function useAppUpdate(): {
  status: AppUpdateStatus
  checkForUpdate: () => void
} {
  const [status, setStatus] = useState<AppUpdateStatus>('idle')
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const checkForUpdate = useCallback(() => {
    // Повторный клик по кнопке не должен запускать вторую проверку.
    if (status !== 'idle') return
    setStatus('checking')

    void (async () => {
      try {
        const registration =
          'serviceWorker' in navigator
            ? await navigator.serviceWorker.getRegistration()
            : undefined

        // Без Service Worker (или пока он не зарегистрирован) честный путь —
        // просто перезагрузка: index.html отдаётся с no-cache, поэтому свежий
        // бандл приедет.
        if (!registration) {
          window.location.reload()
          return
        }

        // Если воркер УЖЕ ждёт — применяем его сразу, не трогая `update()`.
        // Это и есть случай владельца: ожидающий воркер был, а код всё равно
        // шёл в `update()` и вис на нём, хотя обновлять было что.
        let waiting = registration.waiting

        if (!waiting) {
          await withTimeout(registration.update(), UPDATE_TIMEOUT_MS)
          waiting = await waitForWaiting(registration, INSTALL_TIMEOUT_MS)
        }

        if (!waiting) {
          // Воркер молчит — спрашиваем сервер напрямую. Если там сборка новее,
          // обычной перезагрузки достаточно: `index.html` отдаётся с
          // `no-store`, свежий бандл приедет и без Service Worker. Ровно этот
          // путь спасает в Safari, где SW не отвечает.
          const server = await fetchServerVersion()
          if (shouldOfferUpdate(__APP_VERSION__, server)) {
            window.location.reload()
            return
          }
          if (!alive.current) return
          setStatus('idle')
          // Два исхода нельзя смешивать: «проверили, нового нет» — это
          // «последняя версия»; «узнать не удалось» — нет. Сказать второму
          // «у вас последняя версия» значит соврать тому, кто пришёл
          // обновляться.
          if (server === null) {
            toast.error('Не удалось проверить обновления', {
              description: 'Попробуйте ещё раз или перезагрузите страницу.',
            })
          } else {
            toast.success('У вас последняя версия')
          }
          return
        }

        if (alive.current) setStatus('applying')
        waiting.postMessage({ type: 'SKIP_WAITING' })
        await waitForController(CONTROLLER_TIMEOUT_MS)
        window.location.reload()
      } catch {
        // Чаще всего — офлайн: registration.update() бросает на сетевой ошибке.
        if (!alive.current) return
        setStatus('idle')
        toast.error('Не удалось проверить обновления', {
          description: 'Проверьте соединение и попробуйте ещё раз.',
        })
      }
    })()
  }, [status])

  return { status, checkForUpdate }
}

/** Версия на сервере; `null` — узнать не удалось. */
async function fetchServerVersion(): Promise<string | null> {
  try {
    const res = await withTimeout(
      fetch('/version.json', { cache: 'no-store' }),
      UPDATE_TIMEOUT_MS,
    )
    if (res === TIMEOUT || !res.ok) return null
    const data = (await res.json()) as { version?: string }
    return data.version ?? null
  } catch {
    return null
  }
}

/**
 * Ждёт воркер в состоянии `waiting`.
 *
 * `registration.update()` резолвится, когда новый воркер только НАЧАЛ
 * устанавливаться, поэтому сразу после него `waiting` обычно ещё пуст —
 * проверять его одним махом значило бы почти всегда говорить «у вас
 * последняя версия». Возвращает `null`, когда обновления нет.
 */
function waitForWaiting(
  registration: ServiceWorkerRegistration,
  timeoutMs: number,
): Promise<ServiceWorker | null> {
  if (registration.waiting) return Promise.resolve(registration.waiting)

  const installing = registration.installing
  if (!installing) return Promise.resolve(null)

  return new Promise((resolve) => {
    const done = (value: ServiceWorker | null) => {
      window.clearTimeout(timer)
      installing.removeEventListener('statechange', onStateChange)
      resolve(value)
    }
    const onStateChange = () => {
      // `installed` = встал в очередь и ждёт активации. `redundant` = сборка
      // не доехала (упала установка) — обновлять нечего.
      if (installing.state === 'installed') done(registration.waiting ?? installing)
      else if (installing.state === 'redundant') done(null)
    }
    const timer = window.setTimeout(() => done(registration.waiting), timeoutMs)
    installing.addEventListener('statechange', onStateChange)
  })
}

/**
 * Ждёт смены контроллера после `SKIP_WAITING`, но не дольше таймаута:
 * в PWA на iOS `controllerchange` иногда не приходит вовсе, и перезагрузка
 * по таймауту — единственный способ не подвесить кнопку навсегда.
 */
function waitForController(timeoutMs: number): Promise<void> {
  if (!('serviceWorker' in navigator)) return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      window.clearTimeout(timer)
      navigator.serviceWorker.removeEventListener('controllerchange', done)
      resolve()
    }
    const timer = window.setTimeout(done, timeoutMs)
    navigator.serviceWorker.addEventListener('controllerchange', done)
  })
}
