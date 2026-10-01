import { useEffect } from 'react'

import { keyboardCssVars, keyboardInset } from '@/lib/keyboardInset'

/**
 * Следит за `window.visualViewport` и пишет на `<html>` переменные
 * `--kb-inset` / `--vv-height`, по которым мобильные шторки (`BottomSheet`,
 * `DialogContent` ниже lg) садятся на верх экранной клавиатуры, а не на низ
 * layout viewport под ней. Монтируется ОДИН раз в `Shell`.
 *
 * Значения читаются В МОМЕНТ события (не кэшируются): так работает и мок на
 * стенде (`Object.defineProperty(window.visualViewport, 'height', …)` +
 * `dispatchEvent(new Event('resize'))`). `resize` и `scroll` приходят парой,
 * при pinch `scroll` летит 60 Гц — от шторма защищает запись ТОЛЬКО при
 * изменении (custom property на `:root` инвалидирует стили поддерева); при
 * pinch `scale ≠ 1` даёт тот же нулевой inset, записи нет. Без rAF
 * намеренно: в скрытом документе кадры не приходят вовсе, и первая запись
 * откладывалась бы до показа — на стенде это выглядело как «хук не работает».
 */
export function useKeyboardInset(): void {
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const root = document.documentElement
    let last = ''
    const apply = () => {
      const vars = keyboardCssVars(
        keyboardInset({
          innerHeight: window.innerHeight,
          vvHeight: vv.height,
          vvOffsetTop: vv.offsetTop,
          scale: vv.scale,
        }),
      )
      const key = `${vars['--kb-inset']}|${vars['--vv-height']}`
      if (key === last) return
      last = key
      for (const [name, value] of Object.entries(vars)) root.style.setProperty(name, value)
    }
    vv.addEventListener('resize', apply)
    vv.addEventListener('scroll', apply)
    apply()
    return () => {
      vv.removeEventListener('resize', apply)
      vv.removeEventListener('scroll', apply)
      root.style.removeProperty('--kb-inset')
      root.style.removeProperty('--vv-height')
    }
  }, [])
}
