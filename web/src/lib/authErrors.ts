import {
  MissingVerifierError,
  TokenExchangeError,
} from '@signaris/auth-client/browser'

/**
 * Текст экрана «вход не завершился» — для человека, а не для лога.
 *
 * До 0.12 `AuthCallback` печатал `e.message` как есть, и это работало, пока
 * либа роняла обмен своим же текстом. С 0.12 сообщения английские
 * («no PKCE verifier for this login attempt», «Token exchange failed: 400») —
 * показывать их нельзя, а выбрасывать совсем тоже: Sentry выключен, и консоль
 * остаётся единственным каналом диагностики с телефона (то же решение, что у
 * `ErrorFallback`). Поэтому здесь — текст для экрана, техническое сообщение
 * пишет вызывающий в `console.error`.
 *
 * Чистая функция и отдельный файл — потому что ветка «кода в адресе нет вовсе»
 * неочевидна и обязана быть под тестом: с 0.12 `handleCallback` стирает код из
 * адреса на 4xx и на `MissingVerifierError`, так что перезагрузка страницы —
 * самая частая реакция человека на экран ошибки — приводит уже сюда, а не в
 * PKCE-ветку.
 */

/** Текст либы, когда в адресе нет параметра `code` (обмена не было вовсе). */
const NO_CODE = 'no authorization code in callback'

export function authCallbackMessage(err: unknown): string {
  // Кода в адресе нет: либо ссылку открыли повторно уже после обмена, либо
  // 0.12 сам убрал сожжённый код. Просить «попробовать ещё раз» здесь нечестно
  // — этой ссылке уже ничем не помочь, нужен новый вход.
  if (err instanceof Error && err.message === NO_CODE) {
    return 'Ссылка для входа устарела. Начните вход заново.'
  }
  // Для `state` нет записи попытки: вход начинали в другом браузере или
  // хранилище почистили между стартом и возвратом. Обмена не было — код цел,
  // но предъявить его нечем.
  if (err instanceof MissingVerifierError || nameOf(err) === 'MissingVerifierError') {
    return 'Не удалось завершить вход. Начните вход заново.'
  }
  // 5xx — auth не ответил, код, возможно, ещё жив: повтор осмыслен. На 4xx он
  // уже сожжён, и звать «ещё раз» тем же кодом бессмысленно (ровно так копился
  // повтор одного кода 03.09 и 09.09).
  if (isTokenExchangeError(err)) {
    return err.status >= 500
      ? 'auth.signaris.ru не ответил. Попробуйте войти ещё раз.'
      : 'Не удалось завершить вход. Начните вход заново.'
  }
  return 'Не удалось завершить вход.'
}

/**
 * Имя класса как страховка к `instanceof`: если в бандл однажды попадут две
 * копии либы (разные версии у зависимостей), `instanceof` даст false при верном
 * по смыслу объекте, и человек получит невнятный общий текст.
 */
function nameOf(err: unknown): string | null {
  return err instanceof Error ? err.name : null
}

function isTokenExchangeError(err: unknown): err is TokenExchangeError {
  if (err instanceof TokenExchangeError) return true
  return (
    nameOf(err) === 'TokenExchangeError' &&
    typeof (err as { status?: unknown }).status === 'number'
  )
}
