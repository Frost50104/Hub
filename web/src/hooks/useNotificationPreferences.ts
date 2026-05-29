import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import {
  notificationsApi,
  type NotificationPrefs,
  type PreferencesMap,
} from '@/lib/notifications'

export function useNotificationPreferences(): UseQueryResult<NotificationPrefs> {
  return useQuery({
    queryKey: ['notifications', 'preferences'],
    queryFn: () => notificationsApi.getPreferences(),
    staleTime: 60_000,
  })
}

export function useSetNotificationPreferences() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (prefs: PreferencesMap) => notificationsApi.setPreferences(prefs),
    onSuccess: (data) => {
      qc.setQueryData(['notifications', 'preferences'], data)
    },
  })
}
