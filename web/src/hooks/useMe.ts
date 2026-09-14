import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { useEffect } from 'react'

import { api } from '@/lib/api'
import { clearSentryUser, identifySentryUser } from '@/lib/sentry'
import type { Theme } from '@/lib/theme'

export interface MeProfile {
  id: string
  org_role: 'employee' | 'tu' | 'franchisee_owner' | 'office'
  content_role: 'none' | 'author' | 'publisher'
  status: 'active' | 'archived'
  position_id: string | null
  store_id: string | null
  status_text: string | null
}

export interface Me {
  employee_id: string
  email: string
  full_name: string
  tenant_id: string
  tenant_slug: string
  hub_role: 'admin' | 'member' | 'viewer' | null
  /** Публичный аватар из auth; 404 у аккаунтов без фото — фолбэк на инициалы. */
  avatar_url: string
  /** Learn-профиль (HR-карточка); null у юзеров без hub-роли. */
  profile: MeProfile | null
  /** Карточка с этим email в архиве — требуется восстановление админом. */
  profile_needs_restore: boolean
  /** Может создавать проекты и папки (admin или офис/ТУ/франчайзи) — считает
   *  сервер (`project_access.can_create_project`), фронт правило не выводит. */
  can_create_projects: boolean
  /** Скрытый персональный проект «Личное» — источник секции на /my.
   *  Optional, а не `string | null`: старый бэкенд в окне деплоя поля не
   *  отдаёт, и strict-тип врал бы про рантайм. */
  personal_project_id?: string | null
  /** Готовые ПОДПИСАННЫЕ ссылки на инструкции (какие — решает сервер по роли).
   *  Optional по той же причине, что и `personal_project_id`. */
  guides?: { kind: string; title: string; url: string }[]
  /** Тема оформления АККАУНТА (ОС 09.09). Три состояния, и все три значимы:
   *  поля нет — старый бэкенд, синхронизации нет; null — выбор не сделан,
   *  можно засеять локальный; значение — сервер решил (`lib/themeSync.ts`). */
  theme?: Theme | null
}

/** Общие опции запроса: их же берёт префетч на экране auth-колбэка, чтобы
 *  приложение открылось сразу в теме вошедшего, а не в теме устройства.
 *  `signal` обязателен — без него `cancelQueries` в мутации темы половинчат:
 *  отменённый запрос доживает и перетирает свежий выбор ответом со старым. */
export const meQueryOptions = {
  queryKey: ['me'] as const,
  queryFn: ({ signal }: { signal?: AbortSignal }) =>
    api.get<Me>('/me', { signal }).then((r) => r.data),
  staleTime: 5 * 60_000,
}

export function useMe(): UseQueryResult<Me> {
  const query = useQuery(meQueryOptions)

  useEffect(() => {
    if (query.data) {
      identifySentryUser({
        id: query.data.employee_id,
        email: query.data.email,
        username: query.data.full_name,
      })
    } else if (query.isError) {
      clearSentryUser()
    }
  }, [query.data, query.isError])

  return query
}
