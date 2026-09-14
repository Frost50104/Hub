import { cn } from '@/lib/cn'

/**
 * Ряд взаимоисключающих вариантов прямо в форме: приоритет задачи,
 * периодичность повтора. Активный — амбер-заливка с обводкой, а не
 * бейдж: это ЗНАЧЕНИЕ поля, а не статус объекта.
 */
export function OptionButton({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean
  disabled: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'inline-flex min-h-[30px] items-center rounded-lg px-2.5 text-[13px] font-semibold transition-colors',
        disabled ? 'cursor-default' : 'cursor-pointer',
        active
          ? 'bg-amber/30 text-text shadow-[inset_0_0_0_1px_color-mix(in_srgb,rgb(var(--amber))_55%,transparent)]'
          : disabled
            ? 'bg-tint text-text2'
            : 'bg-surface text-text2 hover:text-text',
      )}
    >
      {children}
    </button>
  )
}
