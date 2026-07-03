import { MutationCache, QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { extractErrorDetail } from '@/lib/errors'

// Глобальная сетка безопасности: любая упавшая мутация показывает тост,
// чтобы действие пользователя не терялось молча. Хук может переопределить
// заголовок через meta.errorMessage или целиком забрать обработку себе
// через meta.suppressGlobalError (тогда тост обязан показать сам вызывающий).
export const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (mutation.meta?.suppressGlobalError) return
      const title =
        typeof mutation.meta?.errorMessage === 'string'
          ? mutation.meta.errorMessage
          : 'Не удалось сохранить изменения'
      toast.error(title, { description: extractErrorDetail(error) })
    },
  }),
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      gcTime: 5 * 60_000,
    },
  },
})
