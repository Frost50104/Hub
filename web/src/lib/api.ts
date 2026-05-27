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

attachAxiosAuth(api, authClient)
