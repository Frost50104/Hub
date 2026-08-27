import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

/**
 * Список «подпись — значение» для экранов настроек и карточек.
 *
 * Именно `<dl>` с рядами 11×14px и радиусом 10, а НЕ мобильный блок свойств
 * (`PropertyRows`): у того ряд 48px и правый отступ зарезервирован под
 * контрол, из-за чего текстовые значения прилипали к рамке. Решение принято на
 * макете «Настройки», здесь оно вынесено из `pages/settings/AccountTab.tsx`,
 * чтобы у одного силуэта не завелось два рисователя (урок `ProjectKeyChip`).
 *
 * `shrink-0` не косметика: блок несёт `overflow-hidden` и обычно лежит
 * flex-элементом внутри колонки `flex-1` — без него минимальная высота
 * схлопывается в пару пикселей.
 */
export function InfoRows({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <dl
      className={cn(
        'm-0 shrink-0 overflow-hidden rounded-[10px] border border-glass-border',
        className,
      )}
    >
      {children}
    </dl>
  )
}

export function InfoRow({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-hair px-3.5 py-[11px] first:border-t-0">
      <dt className="text-[15px] text-text2">{label}</dt>
      <dd className="m-0 min-w-0 text-right text-[15px] font-semibold text-text">
        {children}
      </dd>
    </div>
  )
}
