import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Switch } from '@/components/ui/Switch'
import { usePush } from '@/hooks/usePush'
import {
  useNotificationPreferences,
  useSetNotificationPreferences,
} from '@/hooks/useNotificationPreferences'
import {
  NOTIFICATION_KINDS,
  NOTIFICATION_KIND_LABEL,
  type NotificationKind,
  type PreferencesMap,
} from '@/lib/notifications'

export function NotificationsSettingsTab() {
  const prefsQuery = useNotificationPreferences()
  const setPrefs = useSetNotificationPreferences()
  const { permission, subscribed, subscribe, unsubscribe } = usePush()

  if (prefsQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text2">
        <Loader2 className="h-4 w-4 animate-spin" /> Загружаем настройки…
      </div>
    )
  }

  if (prefsQuery.isError) {
    return (
      <p className="text-sm text-red">
        Не удалось загрузить настройки уведомлений. Обновите страницу.
      </p>
    )
  }

  const prefs: PreferencesMap = prefsQuery.data?.prefs ?? {}

  const setChannel = (
    kind: NotificationKind,
    channel: 'push' | 'in_app',
    value: boolean,
  ) => {
    const current = prefs[kind] ?? { push: true, in_app: true }
    const next: PreferencesMap = { ...prefs, [kind]: { ...current, [channel]: value } }
    setPrefs.mutate(next)
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <h2 className="font-display text-lg font-semibold text-text">
          Это устройство
        </h2>
        {permission === 'unsupported' && (
          <p className="text-sm text-text2">
            Браузер не поддерживает push-уведомления. На iPhone — добавьте Hub
            на главный экран и откройте оттуда.
          </p>
        )}
        {permission === 'denied' && (
          <p className="text-sm text-text2">
            Push заблокирован в настройках браузера. Разрешите уведомления для{' '}
            <code>hub.signaris.ru</code>, чтобы получать их на это устройство.
          </p>
        )}
        {permission === 'default' && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-glass-border bg-surface p-3">
            <p className="text-sm text-text2">
              Push-уведомления ещё не подключены на этом устройстве.
            </p>
            <Button
              size="sm"
              onClick={async () => {
                try {
                  const ok = await subscribe()
                  if (ok) toast.success('Уведомления включены')
                  else toast.message('Браузер не дал разрешение')
                } catch (err) {
                  toast.error('Не удалось подписаться', {
                    description: (err as Error).message,
                  })
                }
              }}
            >
              Включить
            </Button>
          </div>
        )}
        {permission === 'granted' && subscribed && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-glass-border bg-surface p-3">
            <p className="text-sm text-text">
              Push-уведомления включены на этом устройстве.
            </p>
            <Button
              size="sm"
              variant="ghost"
              onClick={async () => {
                try {
                  await unsubscribe()
                  toast.success('Отписались от push на этом устройстве')
                } catch (err) {
                  toast.error('Не удалось отписаться', {
                    description: (err as Error).message,
                  })
                }
              }}
            >
              Отписаться
            </Button>
          </div>
        )}
        {permission === 'granted' && !subscribed && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-glass-border bg-surface p-3">
            <p className="text-sm text-text2">
              Разрешение дано, но подписки нет — браузер мог её сбросить.
            </p>
            <Button
              size="sm"
              onClick={async () => {
                try {
                  const ok = await subscribe()
                  if (ok) toast.success('Подписались')
                } catch (err) {
                  toast.error('Не удалось подписаться', {
                    description: (err as Error).message,
                  })
                }
              }}
            >
              Подписаться
            </Button>
          </div>
        )}
      </div>

      <div className="space-y-3">
        <h2 className="font-display text-lg font-semibold text-text">События</h2>
        <p className="text-sm text-text2">
          Раздельно отключайте push (звуковое уведомление на устройстве) и
          in-app (запись во «Входящие»). По умолчанию оба канала включены.
        </p>

        <div className="overflow-hidden rounded-lg border border-glass-border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-xs uppercase tracking-wider text-text3">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Событие</th>
                <th className="w-16 px-3 py-2 text-center font-semibold">Push</th>
                <th className="w-16 px-3 py-2 text-center font-semibold">In-app</th>
              </tr>
            </thead>
            <tbody>
              {NOTIFICATION_KINDS.map((kind, idx) => {
                const pref = prefs[kind] ?? { push: true, in_app: true }
                return (
                  <tr
                    key={kind}
                    className={
                      idx % 2 === 0
                        ? 'bg-transparent'
                        : 'bg-glass/40'
                    }
                  >
                    <td className="px-3 py-2.5 text-text">
                      {NOTIFICATION_KIND_LABEL[kind]}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <Switch
                        checked={pref.push}
                        onCheckedChange={(v) => setChannel(kind, 'push', v)}
                        disabled={setPrefs.isPending}
                        aria-label={`Push для «${NOTIFICATION_KIND_LABEL[kind]}»`}
                      />
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <Switch
                        checked={pref.in_app}
                        onCheckedChange={(v) => setChannel(kind, 'in_app', v)}
                        disabled={setPrefs.isPending}
                        aria-label={`In-app для «${NOTIFICATION_KIND_LABEL[kind]}»`}
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
