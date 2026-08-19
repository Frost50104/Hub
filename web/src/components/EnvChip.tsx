import { currentEnvLabel } from '@/lib/appEnv'

/**
 * Плашка «это не прод».
 *
 * На проде рендерит `null`, а в прод-сборке ветка вырезается целиком как
 * мёртвый код (`__APP_MODE__` — compile-time константа).
 *
 * Монтируется в main.tsx рядом с Toaster/UpdateBanner, а НЕ внутри Shell:
 *   - покрывает и /login, и /auth/callback, и публичную /p/:token — они вне
 *     Shell (App.tsx), а перепутать окружение можно и на них;
 *   - гарантированно не попадает внутрь `.glass`-предка: backdrop-filter
 *     создаёт containing block и превращает `fixed` в `absolute` (на этом
 *     уже горел DragOverlay в сайдбаре).
 *
 * Позиция: снизу слева на мобильном — справа внизу живёт FAB «+»
 * (`fixed right-4 z-30`), а слева внизу на десктопе — блок профиля в
 * сайдбаре, поэтому на `lg` уходим вправо. Отступ снизу считается по той же
 * формуле safe-area, что у FAB (4rem против его 4.5rem — чип ниже кнопки и
 * с зазором над таб-баром): без неё чип уезжает под таб-бар и полосу
 * жестов в PWA на iPhone.
 *
 * `z-30` — ниже шторок и диалогов (все z-50) и ниже баннера обновления
 * (z-40): маркер обязан уступать всему, с чем взаимодействуют.
 * `pointer-events-none` — иначе чип съедал бы тапы по строке под собой.
 */
export function EnvChip() {
  const label = currentEnvLabel()
  if (!label) return null

  return (
    <div
      className="pointer-events-none fixed left-3 z-30 select-none rounded-md bg-amber px-2 py-1 font-display text-[10px] font-bold uppercase tracking-wide text-on-amber shadow-lg lg:left-auto lg:right-3"
      style={{ bottom: 'calc(env(safe-area-inset-bottom, 0px) + 4rem)' }}
    >
      {label}
    </div>
  )
}
