import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

import { Button } from '@/components/ui/Button'
import { useAppUpdate } from '@/hooks/useAppUpdate'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { shouldOfferUpdate } from '@/lib/appVersion'
import { noteServerVersion } from '@/lib/serviceWorker'

// 30 с, а не 60: деплоев в день много, а баннер сам ничего не перезагружает —
// узнать об обновлении раньше стало дёшево, и человек применяет его в удобный
// момент. Цена — GET `/version.json` (38 байт, `no-store`) раз в полминуты.
const UPDATE_CHECK_INTERVAL_MS = 30_000

/**
 * Баннер «Доступно обновление».
 *
 * ПОКАЗЫВАТЬ ли баннер, решает сравнение версий, а не состояние воркера
 * (16.09): `__APP_VERSION__` вшит в бандл при сборке, `/version.json` отдаёт
 * сервер, обе величины пишет один `write_version`. Воркер к этому отношения
 * не имеет — и в Safari с зависшей регистрацией (разбор 25.09) баннер
 * работал всё это время, потому что от воркера не зависит.
 *
 * САМ баннер страницу НЕ перезагружает, и это главное его свойство (ОС 16.09
 * «работа не сохраняется, даже если не нажимали кнопку обновить»). Таймеров
 * перезагрузки здесь нет; с 25.09 нет и регистрации воркера через плагин
 * (`useRegisterSW`) — его слушатель `controlling` перезагружал ВСЕ вкладки
 * браузера при клике в одной. Регистрация и пробы воркера живут в
 * `lib/serviceWorker.ts`; опрос версии сообщает туда `noteServerVersion`,
 * от которого и запускается фоновая установка нового воркера.
 *
 * Кнопка «Обновить» идёт через `useAppUpdate` — тот же путь, что «Обновить
 * приложение» в Настройках: заданий воркера не создаёт, установки не ждёт,
 * обновление = перезагрузка страницы со свежим бандлом из сети.
 */
export function UpdateBanner() {
  const isDesktop = useIsDesktop()
  const isTvRoute = useLocation().pathname.startsWith('/p/race/')
  const { status, checkForUpdate } = useAppUpdate()
  const busy = status !== 'idle'
  // Версия на сервере. `null` — узнать не удалось (офлайн, дев-стенд без
  // version.json): тогда молчим, см. `shouldOfferUpdate`.
  const [serverVersion, setServerVersion] = useState<string | null>(null)
  // Версия, отложенная кнопкой «Позже»: откладывается КОНКРЕТНАЯ версия, и
  // следующая новая покажется снова.
  const [dismissed, setDismissed] = useState<string | null>(null)

  // Опрос версии — единственный опрос сервера у баннера; `visibilitychange`
  // лечит замороженные в фоне таймеры iOS PWA.
  useEffect(() => {
    let cancelled = false
    const readVersion = async () => {
      if (!navigator.onLine) return
      try {
        const res = await fetch('/version.json', { cache: 'no-store' })
        if (!res.ok) return
        const data = (await res.json()) as { version?: string }
        if (cancelled || !data.version) return
        setServerVersion(data.version)
        noteServerVersion(data.version, Date.now())
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
