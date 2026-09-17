import { attachAxiosAuth } from '@signaris/auth-client/browser'
import axios from 'axios'

import { authClient } from './auth'

// `baseURL: '/api'` — vite-dev и nginx-prod проксируют /api → backend.
// `X-Auth-Mode: api` — говорит auth-стороне отдавать refresh-token в теле
// ответа (а не в cookie); PWA standalone (iOS) cookie jar обособлен от
// браузера, поэтому без этого refresh не подхватится.
export const api = axios.create({
  baseURL: '/api',
  headers: {
    'X-Auth-Mode': 'api',
  },
})

/**
 * Куда вернуть человека после входа, начатого не им, а перехватчиком.
 *
 * `attachAxiosAuth` зовёт `startLogin()` БЕЗ аргумента, а отдельного гейта,
 * который уводил бы на `/login` с сохранением адреса, у Hub нет: `/login`
 * достижим только логаутом и ссылкой с экрана ошибки. Поэтому протухшая
 * посреди работы сессия возвращала на `/` — открытая задача, доска и фильтры
 * терялись. Отдаём текущий адрес сами; путь всё равно проходит через
 * `sanitizeReturnPath` внутри либы, так что `/login` и `/auth/*` в returnPath
 * не попадут и петли login→callback→login не будет.
 *
 * С либы 0.13 она подставляет текущий адрес сама (`returnPath ?? currentPath()`,
 * правка по нашей же заявке), так что обёртка стала СТРАХОВКОЙ, а не
 * единственной причиной. Оставлена сознательно — auth подтвердил, что явный
 * путь по-прежнему важнее и поведение не меняется, а снятие обёртки молча
 * вернуло бы потерю адреса при любом откате либы ниже 0.13.
 */
function currentPath(): string {
  return `${window.location.pathname}${window.location.search}`
}

attachAxiosAuth(api, {
  ...authClient,
  startLogin: (returnPath, opts) =>
    authClient.startLogin(returnPath ?? currentPath(), opts),
})
