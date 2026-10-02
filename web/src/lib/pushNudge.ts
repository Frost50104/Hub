/**
 * Карточка «включите уведомления» — какую ветку показать (чистая логика под vitest).
 *
 * До 02.10 промпт жил только на главной трекера и только для `permission ===
 * 'default'`: сотрудники точек работают в «Обучении», а на iPhone во вкладке
 * Safari push вообще `unsupported` — и о том, что Hub надо добавить на экран
 * «Домой», человек не узнавал. Итог: «заезд стартовал» 02.10 дошёл до 9 из 152.
 */

export type PushPermission = 'unsupported' | 'default' | 'granted' | 'denied'
export type PushNudgeKind = 'ios-install' | 'enable' | 'subscribe' | 'denied'

export interface PushNudgeInput {
  permission: PushPermission
  /** Есть подписка в этом браузере — значимо только при `checked`. */
  subscribed: boolean
  /** `getSubscription()` ответил; на iOS `serviceWorker.ready` может молчать. */
  checked: boolean
  ios: boolean
  standalone: boolean
  /** До какого момента человек нажал «Позже» (ms), null — не нажимал. */
  dismissedUntil: number | null
  now: number
}

/** «Позже» прячет карточку на неделю — не навсегда: до старта гонки остаются дни. */
export const PUSH_NUDGE_DISMISS_MS = 7 * 24 * 60 * 60 * 1000

export const PUSH_NUDGE_DISMISS_KEY = 'hub:push-nudge-dismissed-until'

export function pushNudgeKind(i: PushNudgeInput): PushNudgeKind | null {
  if (i.dismissedUntil !== null && i.dismissedUntil > i.now) return null
  if (i.permission === 'unsupported') return i.ios && !i.standalone ? 'ios-install' : null
  if (i.permission === 'denied') return 'denied'
  if (i.permission === 'default') return 'enable'
  if (!i.checked) return null
  return i.subscribed ? null : 'subscribe'
}

/** iPhone/iPad по UA; iPadOS 13+ представляется Macintosh, но с тачем. */
export function isIosUa(ua: string, maxTouchPoints: number): boolean {
  return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && maxTouchPoints > 1)
}

export interface PushNudgeText {
  title: string
  body: string
  /** Подпись кнопки действия; null — только текст (iOS без экрана «Домой»). */
  action: string | null
}

export function pushNudgeText(kind: PushNudgeKind, race: boolean): PushNudgeText {
  const title = race ? 'Включите уведомления о гонке' : 'Включить уведомления о задачах?'
  const why = race
    ? 'Старт заезда и рекорды вашей точки придут на телефон.'
    : 'Push о назначениях, @упоминаниях и комментариях в задачах, за которыми вы следите.'
  switch (kind) {
    case 'enable':
      return { title, body: why, action: 'Включить' }
    case 'subscribe':
      return { title, body: `${why} Разрешение уже есть — осталось подписать это устройство.`, action: 'Подписаться' }
    case 'ios-install':
      return {
        title,
        body: 'На iPhone уведомления работают только с экрана «Домой»: нажмите «Поделиться» → «На экран “Домой”» и откройте Hub оттуда.',
        action: null,
      }
    case 'denied':
      return { title, body: 'Уведомления заблокированы в браузере. Как разрешить — в настройках.', action: 'Настройки' }
  }
}

export function readDismissedUntil(raw: string | null): number | null {
  if (!raw) return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}
