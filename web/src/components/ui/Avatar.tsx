import { useCallback, useEffect, useSyncExternalStore, type HTMLAttributes } from 'react'

import { avatarUrl } from '@/lib/avatarUrl'
import { cn } from '@/lib/cn'

interface AvatarProps extends HTMLAttributes<HTMLDivElement> {
  name: string | null | undefined
  email?: string | null
  /** Сотрудник, чьё фото показать. Адрес выводится сам (`lib/avatarUrl.ts`). */
  employeeId?: string | null
  /** Готовый URL фото — побеждает `employeeId` (профиль отдаёт его напрямую). */
  src?: string | null
}

function initials(name: string | null | undefined, email: string | null | undefined): string {
  const source = name?.trim() || email?.split('@')[0] || '?'
  const parts = source.split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]?.toUpperCase() ?? '').join('') || '?'
}

// Есть ли по этому адресу фото. Стор общий на приложение, потому что аватаров
// на экране бывают тысячи (список задач не виртуализирован: 2500 строк по три
// исполнителя), а РАЗЛИЧНЫХ людей среди них — единицы.
//
// Отсюда же выбор «инициалы по умолчанию, фото после подтверждения», а не
// прежний `<img onError>`: фото есть далеко не у всех, и на большом списке
// сотни падающих картинок означали бы сотни отдельных setState и волну пустых
// кружков до срабатывания onError. Проба уходит одна на адрес.
const known = new Map<string, { ok: boolean; at: number }>()
const probing = new Set<string>()
const listeners = new Map<string, Set<() => void>>()

// Сколько помним «фото нет». Ровно столько же держит его auth
// (`cache-control: public, max-age=60` у 404), и это не мелочь: без срока
// холодный старт PWA без сети отравил бы все аватары до перезагрузки вкладки,
// а загруженное только что фото не появилось бы вовсе. Успех не перепроверяем
// — картинка уже в HTTP-кэше.
const MISS_TTL_MS = 60_000

function hasPhoto(url: string): boolean | undefined {
  // Снапшот для useSyncExternalStore обязан быть стабильным между вызовами,
  // поэтому срок жизни промаха проверяет проба, а не эта функция: значение,
  // протухающее само по себе, дало бы React'у два разных ответа в одном
  // рендере.
  return known.get(url)?.ok
}

function settle(url: string, ok: boolean) {
  probing.delete(url)
  known.set(url, { ok, at: Date.now() })
  listeners.get(url)?.forEach((notify) => notify())
}

function probe(url: string) {
  // Идемпотентно: в dev StrictMode вызывает эффекты дважды, и без этой
  // проверки на каждого человека уходило бы по две пробы.
  if (probing.has(url)) return
  const hit = known.get(url)
  // Успех не перепроверяем никогда, промах — не чаще раза в минуту. Проба
  // повторяется при следующем монтировании аватара (переход по разделам,
  // новый список), поэтому вернувшаяся сеть и только что загруженное фото
  // доезжают без перезагрузки вкладки.
  if (hit && (hit.ok || Date.now() - hit.at <= MISS_TTL_MS)) return
  probing.add(url)
  const img = new Image()
  const finish = (ok: boolean) => {
    // Обнуляем обработчики: без этого декодированный битмап держится
    // ссылкой на живой Image и не собирается сборщиком мусора.
    img.onload = null
    img.onerror = null
    settle(url, ok)
  }
  img.onload = () => finish(true)
  img.onerror = () => finish(false)
  img.src = url
}

function subscribe(url: string, notify: () => void): () => void {
  // Подписчики per-url, а не общим списком: ответ пробы будит только те
  // аватары, которые показывают этого человека.
  let set = listeners.get(url)
  if (!set) listeners.set(url, (set = new Set()))
  set.add(notify)
  return () => {
    set.delete(notify)
    if (set.size === 0) listeners.delete(url)
  }
}

function useHasPhoto(url: string | undefined): boolean {
  const subscribeToUrl = useCallback(
    (notify: () => void) => (url ? subscribe(url, notify) : () => {}),
    [url],
  )
  // Снапшот — примитив, а не объект: иначе useSyncExternalStore зациклится.
  const snapshot = useCallback(() => (url ? hasPhoto(url) : undefined), [url])
  useEffect(() => {
    if (url) probe(url)
  }, [url])
  return useSyncExternalStore(subscribeToUrl, snapshot) === true
}

export function Avatar({ name, email, employeeId, src, className, ...props }: AvatarProps) {
  const url = src || avatarUrl(employeeId)
  const hasPhoto = useHasPhoto(url ?? undefined)

  return (
    <div
      className={cn(
        // Заливка --av-fill НЕПРОЗРАЧНАЯ: полупрозрачная (amber/20) в стеке
        // просвечивала инициалы соседа. Краска --text, а не --amber: амбер на
        // амбер-тинте даёт 1,7:1 в светлой теме.
        'inline-flex h-6 w-6 select-none items-center justify-center overflow-hidden rounded-full bg-av-fill text-[12px] font-semibold uppercase text-text',
        className,
      )}
      title={name || email || undefined}
      {...props}
    >
      {url && hasPhoto ? (
        <img
          src={url}
          alt=""
          className="h-full w-full object-cover"
          // Проба уже сказала «фото есть», но картинку могли вытеснить из кэша
          // между пробой и показом — тогда возвращаемся к инициалам.
          onError={() => settle(url, false)}
        />
      ) : (
        initials(name, email)
      )}
    </div>
  )
}
