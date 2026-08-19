import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

/** Сколько ждём, пока найденное обновление доустановится до `waiting`. */
const INSTALL_TIMEOUT_MS = 20_000
/** Сколько ждём смены контроллера после SKIP_WAITING, прежде чем перезагрузить силой. */
const CONTROLLER_TIMEOUT_MS = 3_000

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

        await registration.update()
        const waiting = await waitForWaiting(registration, INSTALL_TIMEOUT_MS)

        if (!waiting) {
          if (!alive.current) return
          setStatus('idle')
          toast.success('У вас последняя версия')
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
