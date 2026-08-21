import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/cn'
import { HUB_ROLE_BADGE } from '@/lib/learn'

/**
 * Чип hub-роли у профиля в футере сайдбаров (решение владельца 2026-08-21:
 * роль — маленьким чипом рядом с именем, а не строкой под логотипом).
 * Силуэт бейджа спеки (22px, 11/700 uppercase): админ — амбер, остальные —
 * нейтральная поверхность. Словарь — HUB_ROLE_BADGE (его же читает SettingsPage).
 */
export function HubRoleChip({
  role,
  className,
}: {
  role: 'admin' | 'member' | 'viewer'
  className?: string
}) {
  return (
    <Badge
      variant={role === 'admin' ? 'default' : 'secondary'}
      className={cn('shrink-0', className)}
      title={HUB_ROLE_BADGE[role]}
    >
      {HUB_ROLE_BADGE[role]}
    </Badge>
  )
}
