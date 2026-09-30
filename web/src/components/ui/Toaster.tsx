import { Branch as DismissableLayerBranch } from '@radix-ui/react-dismissable-layer'
import { createPortal } from 'react-dom'
import { Toaster as SonnerToaster } from 'sonner'

import { useTheme } from '@/lib/theme'

/**
 * Тостер живёт ПОРТАЛОМ в `body`, а не там, где стоит в дереве.
 *
 * Без этого его не видно из-под карточки задачи, и никакой z-index не
 * помогает: `#root` — стекинг-контекст (`position:relative; z-index:1` в
 * `styles/brand.css`, поднимает приложение над dot-grid'ом `body::before`).
 * Всё внутри него, включая `z-index: 999999999` самого sonner, прижато к
 * уровню 1, а карточка задачи уезжает порталом Radix прямо в `body` со своим
 * `z-index: 40` — и 40 в корневом контексте всегда больше единицы. Тост
 * оказывался ПОД карточкой (и под мобильным листом, z-50).
 *
 * В `body` его собственный z-index наконец с чем сравнивать.
 *
 * Под модальным слоем Radix (карточка задачи на телефоне, шторки, `Dialog`,
 * меню) тост ещё и обязан быть КЛИКАБЕЛЬНЫМ, и для этого нужны ДВЕ вещи
 * (ОС 30.09: «Отменить» у «Задача выполнена» не нажать, нажимается то, что
 * за тостом»):
 *
 * 1. `pointer-events-auto` на обёртке. Модальный `DismissableLayer` ставит
 *    `body { pointer-events: none }`, а тостер, живя в `body` вне слоя,
 *    НАСЛЕДУЕТ его: у sonner нет своего `pointer-events: auto` (единственное
 *    его правило — `[data-visible=false] { pointer-events: none }`, оно
 *    стоит на самом `li` и продолжит держать скрытые тосты стопки
 *    инертными). Тап проваливался сквозь тост в шапку карточки — на
 *    телефоне ровно в «…» и «Закрыть», под шторкой — в оверлей.
 * 2. `DismissableLayer.Branch`. Вернув тосту клики, мы сделали бы тап по
 *    нему «кликом снаружи» слоя — лист закрывался бы. Ветка — родной
 *    механизм Radix (так устроен его собственный `Toast.Viewport`):
 *    `usePointerDownOutside`/`useFocusOutside` проверяют `context.branches`
 *    до вызова обработчиков и молча выходят, если цель внутри ветки; на
 *    touch отложенный `click` несёт цель исходного `pointerdown`. Контекст у
 *    Radix — модульный объект без Provider, поэтому ветка видна всем слоям
 *    через порталы. Точечные `onInteractOutside` в каждом диалоге
 *    отвергнуты: их надо помнить в каждом новом `DialogPrimitive.Content`.
 *
 * Единственный тихий отказ ветки — ВТОРАЯ копия
 * `@radix-ui/react-dismissable-layer` в node_modules (Radix пинит точные
 * версии; наш диапазон — caret): ветка регистрировалась бы в чужом `Set`,
 * диалоги снова закрывались бы от тапа, а `pointer-events` продолжал бы
 * работать. Сторожит `lib/radixSingleCopy.test.ts` по package-lock.
 */
export function Toaster() {
  const theme = useTheme((s) => s.theme)
  return createPortal(
    // Обёртка — обычный div нулевой высоты без transform/filter: containing
    // block для `position: fixed` у `<ol>` sonner не создаёт, `offset` и
    // `mobileOffset` (CSS-переменные на самом `<ol>`) не задеты.
    <DismissableLayerBranch className="pointer-events-auto">
      <SonnerToaster
        // Сверху, а не снизу: на мобильном sonner растягивает тост на всю
        // ширину и он садился ровно на таб-бар, перекрывая основную
        // навигацию (ОС 19.08).
        //
        // По центру, а не справа: у правого края живёт карточка задачи —
        // непрозрачная панель 560px (TaskDetailDrawer), и тост ложился ровно
        // на её ключ, колокол, «…» и крестик, держа их закрытыми все четыре
        // секунды. Прятал он, а не его: у контейнера sonner z-index
        // 999999999, он выше и панели (z-40), и мобильного листа (z-50).
        // По центру перекрывается максимум заголовок страницы.
        position="top-center"
        theme={theme}
        // Только top: при центрировании горизонтальный отступ ни на что не
        // влияет, а в коде выглядел бы работающим.
        offset={{ top: '1rem' }}
        // Мобильные отступы у sonner СВОИ (ниже 600px). Без safe-area тост в
        // PWA на iPhone уехал бы под часы — зеркало той же ошибки, только
        // сверху.
        mobileOffset={{
          top: 'calc(env(safe-area-inset-top, 0px) + 0.75rem)',
          left: '0.75rem',
          right: '0.75rem',
        }}
        toastOptions={{
          classNames: {
            toast: 'glass-solid !border-glass-border !text-text',
            description: '!text-text2',
            actionButton: '!bg-amber !text-on-amber',
            cancelButton: '!bg-surface !text-text2',
            error: '!border-red/50',
            success: '!border-green/50',
          },
        }}
      />
    </DismissableLayerBranch>,
    document.body,
  )
}
