import { cva, type VariantProps } from 'class-variance-authority'
import { type HTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

/**
 * Один силуэт на все статусы (спека редизайна): высота 22px, радиус 6,
 * 11/700 uppercase +0.08em. Варианты различаются только фоном и краской.
 *
 * Рецепт семантики — плотная подложка + краска, которая флипается вместе с
 * темой (`--bg`); для амбера краска фиксированная (`--on-amber`), потому что
 * амбер жёлтый в обеих темах. Тинт под краску того же цвета не используется:
 * amber-на-amber давал 1,73:1, зелёный-на-зелёном 2,7:1 в светлой теме при
 * норме 4,5:1 для 11px. Нейтральные бейджи — `--surface` + `--text2` (6,5:1);
 * `--text3` на тинте 4-6% даёт 2,7:1 и здесь не применяется.
 */
const badgeVariants = cva(
  'inline-flex h-[22px] shrink-0 items-center rounded-md px-2 text-[11px] font-bold uppercase leading-none tracking-[0.08em]',
  {
    variants: {
      variant: {
        default: 'bg-amber text-on-amber',
        success: 'bg-green-deep text-bg',
        destructive: 'bg-red text-bg',
        secondary: 'bg-surface text-text2',
        outline: 'border border-hair text-text2',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
