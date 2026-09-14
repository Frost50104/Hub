import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import type { Me } from '@/hooks/useMe'
import { api } from '@/lib/api'
import {
  readStoredRaw,
  readThemeOwner,
  setThemeLocal,
  THEME_STORAGE_KEY,
  useTheme,
  type Theme,
} from '@/lib/theme'
import { decideThemeSync } from '@/lib/themeSync'

interface Ctx {
  prev: Me | undefined
  prevTheme: Theme
}

function putTheme(theme: Theme): Promise<{ theme: Theme | null }> {
  return api
    .put<{ theme: Theme | null }>('/me/preferences', { theme })
    .then((r) => r.data)
}

/**
 * Сохранить тему на сервере, применив её локально сразу.
 *
 * Три вещи против гонки «щёлкнул тумблер — рефетч /me вернул старое»
 * (`staleTime` 5 мин + глобальный `refetchOnWindowFocus`): `cancelQueries`,
 * оптимистичный `setQueryData` и `signal` в `meQueryOptions`. Убрать любую —
 * и выбор будет иногда откручиваться назад сам собой.
 *
 * При ошибке тема ОТКАТЫВАЕТСЯ: оставить применённой, но не сохранённой —
 * значит отпустить человека в уверенности, что он настроил.
 */
export function useSetTheme(): UseMutationResult<
  { theme: Theme | null },
  unknown,
  Theme,
  Ctx
> {
  const qc = useQueryClient()
  return useMutation<{ theme: Theme | null }, unknown, Theme, Ctx>({
    mutationFn: putTheme,
    onMutate: async (theme) => {
      await qc.cancelQueries({ queryKey: ['me'] })
      const prev = qc.getQueryData<Me>(['me'])
      const prevTheme = useTheme.getState().theme
      setThemeLocal(theme, prev?.employee_id)
      if (prev) qc.setQueryData<Me>(['me'], { ...prev, theme })
      return { prev, prevTheme }
    },
    onError: (_err, _theme, ctx) => {
      if (!ctx) return
      setThemeLocal(ctx.prevTheme, ctx.prev?.employee_id)
      if (ctx.prev) qc.setQueryData<Me>(['me'], ctx.prev)
    },
    onSuccess: (data) => {
      const prev = qc.getQueryData<Me>(['me'])
      if (prev) qc.setQueryData<Me>(['me'], { ...prev, theme: data.theme })
    },
    meta: { errorMessage: 'Не удалось сохранить тему' },
  })
}

/**
 * Привести тему к серверной, когда пришёл `/api/me`.
 *
 * Живёт в `Shell` — корневом лэйауте всех аутентифицированных роутов. До
 * ответа `/me` работает кеш устройства (иначе холодный старт PWA без сети
 * открывался бы не в той теме), после — решает сервер.
 */
export function useThemeSync(me: Me | undefined): void {
  const qc = useQueryClient()
  // Посев (перенос выбора, сделанного до выката) не идемпотентен, а StrictMode
  // в dev прогоняет эффекты дважды — гард обязателен и обязан быть ref'ом.
  const seeded = useRef(false)
  const seed = useMutation<{ theme: Theme | null }, unknown, Theme>({
    mutationFn: putTheme,
    onSuccess: (data) => {
      const prev = qc.getQueryData<Me>(['me'])
      if (prev) qc.setQueryData<Me>(['me'], { ...prev, theme: data.theme })
    },
    // Фоновая гигиена: человек ничего не нажимал, тост ему показывать не за что.
    meta: { suppressGlobalError: true },
  })
  const seedMutate = seed.mutate

  useEffect(() => {
    if (!me) return
    const action = decideThemeSync({
      serverTheme: me.theme,
      localTheme: readStoredRaw(),
      localOwner: readThemeOwner(),
      employeeId: me.employee_id,
      currentTheme: useTheme.getState().theme,
    })
    if (action.kind === 'adopt') {
      setThemeLocal(action.theme, me.employee_id)
    } else if (action.kind === 'seed' && !seeded.current) {
      seeded.current = true
      setThemeLocal(action.theme, me.employee_id)
      seedMutate(action.theme)
    }
  }, [me, seedMutate])

  // Вторая вкладка: `refetchOnWindowFocus` обновляет только просроченные
  // запросы, а `/me` живёт 5 минут — без этого соседняя вкладка держала бы
  // старую тему. Реагируем ТОЛЬКО на непустое валидное значение: при логауте
  // ключ удаляется, и `newValue === null` перекрасил бы вкладку в дефолт.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== THEME_STORAGE_KEY) return
      if (e.newValue !== 'light' && e.newValue !== 'dark') return
      if (e.newValue !== useTheme.getState().theme) setThemeLocal(e.newValue)
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])
}
