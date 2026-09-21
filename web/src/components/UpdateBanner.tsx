import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useRegisterSW } from 'virtual:pwa-register/react'

import { Button } from '@/components/ui/Button'
import { useAppUpdate } from '@/hooks/useAppUpdate'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { shouldOfferUpdate } from '@/lib/appVersion'

// 30 с, а не 60: деплоев в день много, а с 16.09 баннер сам ничего не
// перезагружает — значит узнать об обновлении раньше стало дёшево, и человек
// успевает применить его в удобный момент, а не наткнуться на расхождение с
// бэкендом. Цена — условный GET `sw.js` раз в полминуты на вкладку, обычно 304.
const UPDATE_CHECK_INTERVAL_MS = 30_000

/**
 * Service Worker update banner.
 *
 * SW registered with `registerType: 'prompt'` waits for an explicit
 * `skipWaiting`. This banner polls for new versions every 60s and on
 * `visibilitychange` (iOS PWA freezes background timers, so the focus event
 * is the reliable wake-up), then surfaces a button to activate the new SW.
 *
 * Polling lives in a `useEffect` on `navigator.serviceWorker.ready`, NOT
 * inside `onRegisteredSW` — that callback only fires on first registration,
 * so users with an already-active SW would never get polled.
 *
 * САМ баннер страницу НЕ перезагружает, и это главное его свойство (ОС 16.09:
 * «работа не сохраняется, даже если не нажимали кнопку обновить»). Здесь жил
 * `useEffect`, заводивший `setTimeout(reload, 60_000)` — но привязан он был к
 * `needRefresh`, то есть к ПОЯВЛЕНИЮ баннера, а не к нажатию «Обновить»
 * (задумывалась подстраховка после клика — так написано было в его же
 * комментарии). А `needRefresh` поднимает плагин сам по событию `waiting`,
 * то есть по факту выката: человеку достаточно печатать в этот момент, чтобы
 * через минуту потерять несохранённое. Нажавшего «Позже» спасал cleanup,
 * всех остальных — нет.
 *
 * Кнопка «Обновить» идёт через `useAppUpdate` — тот же путь, что «Обновить
 * приложение» в настройках (21.09). Прежний обработчик (`updateServiceWorker(true)`
 * + `reload` через 1,5 с) не ждал установки нового воркера: пока тот качал
 * прекеш, `SKIP_WAITING` уходил в пустоту (у `workbox-window` без `waiting`
 * вызов пустой), и перезагрузка шла под СТАРЫМ воркером. На «Главной» он
 * отдавал из прекеша старую `index.html`, и баннер возвращался после каждого
 * нажатия (ОС владельца, iPhone). `useAppUpdate` ждёт установку до `waiting`,
 * активирует её и перезагружает гарантированно — по `controllerchange` или
 * силой через 3 с (iOS PWA этого события иногда не шлёт). HTML с той же
 * правки в прекеш не кладётся (`vite.config.ts`), так что и запасная обычная
 * перезагрузка приносит свежую оболочку.
 *
 * ПОКАЗЫВАТЬ ли баннер, решает сравнение версий, а не состояние воркера
 * (16.09). Прежний признак — событие `needRefresh` от плагина — в Safari
 * теряется: у владельца ожидающий воркер БЫЛ, а баннера не было, и там же
 * замерено, что `registration.update()` не резолвится вовсе. Версия от этого
 * свободна: `__APP_VERSION__` вшит в бандл при сборке, `/version.json`
 * отдаётся сервером с `no-store`, пишет обе величины один `write_version`.
 * Событие плагина оставлено вторым признаком — хуже от него не станет.
 */
export function UpdateBanner() {
  const isDesktop = useIsDesktop()
  const isTvRoute = useLocation().pathname.startsWith('/p/race/')
  // `useRegisterSW` вызывается РАДИ РЕГИСТРАЦИИ: виртуальный модуль плагина —
  // единственное место, где регистрируется наш Service Worker (в собранном
  // `index.html` никакой регистрации нет). Из его состояния мы больше ничего
  // не берём: `needRefresh` поднимается на любой смене воркера, в том числе
  // когда бандл у человека уже свежий, — замер на staging 16.09 показал ровно
  // это, баннер висел при совпадающих версиях.
  useRegisterSW()
  const { status, checkForUpdate } = useAppUpdate()
  const busy = status !== 'idle'
  // Версия на сервере. `null` — узнать не удалось (офлайн, дев-стенд без
  // version.json): тогда молчим, см. `shouldOfferUpdate`.
  const [serverVersion, setServerVersion] = useState<string | null>(null)
  // Версия, отложенная кнопкой «Позже»: откладывается КОНКРЕТНАЯ версия, и
  // следующая новая покажется снова.
  const [dismissed, setDismissed] = useState<string | null>(null)

  // Опрос версии живёт ОТДЕЛЬНО от опроса воркера и не зависит от него:
  // в Safari `serviceWorker.ready` и `update()` подводят, а этот путь — нет.
  useEffect(() => {
    let cancelled = false
    const readVersion = async () => {
      if (!navigator.onLine) return
      try {
        const res = await fetch('/version.json', { cache: 'no-store' })
        if (!res.ok) return
        const data = (await res.json()) as { version?: string }
        if (!cancelled && data.version) setServerVersion(data.version)
      } catch {
        // Офлайн или сервер недоступен: прежнее значение не трогаем.
      }
    }
    const id = window.setInterval(() => void readVersion(), UPDATE_CHECK_INTERVAL_MS)
    const onVisible = () => {
      if (document.visibilityState === 'visible') void readVersion()
    }
    document.addEventListener('visibilitychange', onVisible)
    void readVersion()
    return () => {
      cancelled = true
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  useEffect(() => {
    if (!('serviceWorker' in navigator)) return undefined
    let cancelled = false
    let intervalId: number | undefined
    let visListener: (() => void) | undefined

    navigator.serviceWorker.ready
      .then((registration) => {
        if (cancelled || !registration) return
        const check = () => {
          if (navigator.onLine) void registration.update()
        }
        intervalId = window.setInterval(check, UPDATE_CHECK_INTERVAL_MS)
        visListener = () => {
          if (document.visibilityState === 'visible') check()
        }
        document.addEventListener('visibilitychange', visListener)
        // Kick off one check immediately — don't wait the full minute.
        check()
      })
      .catch(() => {
        /* SW not registered — nothing to poll. */
      })

    return () => {
      cancelled = true
      if (intervalId !== undefined) window.clearInterval(intervalId)
      if (visListener) document.removeEventListener('visibilitychange', visListener)
    }
  }, [])

  // ТВ-панель гонки: некому нажать «Обновить» — киоск сверяет версию сам
  // (RaceTvPage). Проверка ПОСЛЕ всех хуков: компонент смонтирован у корня и
  // не перемонтируется при навигации, ранний return менял бы число хуков.
  if (isTvRoute) return null
  if (!shouldOfferUpdate(__APP_VERSION__, serverVersion, dismissed)) return null

  return (
    <div
      className="glass-solid fixed inset-x-4 bottom-4 z-40 flex flex-col gap-3 p-4 shadow-glass sm:left-auto sm:right-4 sm:w-96"
      // Ниже lg таб-бар зафиксирован у нижнего края, и баннер садился прямо
      // на него — в отличие от тоста, висел там до нажатия «Позже», то есть
      // блокировал навигацию. Поднимаем по той же формуле safe-area, что у
      // FAB и чипа окружения. Класс `bottom-4` остаётся для десктопа:
      // инлайн-стиль перебил бы его на всех ширинах.
      style={
        !isDesktop
          ? { bottom: 'calc(env(safe-area-inset-bottom, 0px) + 4.5rem)' }
          : undefined
      }
    >
      <div>
        <p className="font-display text-sm font-semibold text-text">
          Доступно обновление
        </p>
        <p className="text-xs text-text2">
          Установлена новая версия Signaris Hub. Применить сейчас?
        </p>
      </div>
      <div className="flex justify-end gap-2">
        <Button
          variant="ghost"
          size="sm"
          // Пока идёт обновление, «Позже» не нажать: процесс уже запущен и
          // перезагрузит страницу, а спрятанный баннер обещал бы обратное.
          disabled={busy}
          onClick={() => setDismissed(serverVersion)}
        >
          Позже
        </Button>
        <Button size="sm" onClick={checkForUpdate} disabled={busy}>
          {busy ? 'Обновляем…' : 'Обновить'}
        </Button>
      </div>
    </div>
  )
}
