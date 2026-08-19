import { cva, type VariantProps } from 'class-variance-authority'
import { type HTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

/**
 * Чип — значение, а не статус: метка, кастом-поле, дата.
 *
 * Силуэт тот же, что у `Badge` (высота 22, радиус 6, padding 8), но набор
 * 12/600 БЕЗ uppercase: имена меток и значения полей вводит пользователь, и
 * прописные буквы искажали бы его текст. Uppercase 11/700 остаётся за
 * `Badge` — статусом, приоритетом, ролью, архивом.
 *
 * Цвет метки не задаётся классом: он произвольный и считается в
 * `lib/labelChip.ts` (краска по контрасту + затемнение заливки).
 */
const chipVariants = cva(
  'inline-flex shrink-0 items-center rounded-md px-2 text-[12px] font-semibold leading-none',
  {
    variants: {
      variant: {
        neutral: 'bg-surface text-text2',
        outline: 'border border-hair text-text2',
        danger: 'bg-red text-bg',
        /** Заливку и краску даёт inline-style из labelChipColors. */
        custom: '',
      },
      size: {
        sm: 'h-[22px]',
        md: 'h-[26px]',
      },
    },
    defaultVariants: { variant: 'neutral', size: 'sm' },
  },
)

export interface ChipProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof chipVariants> {}

export function Chip({ className, variant, size, ...props }: ChipProps) {
  return (
    <span className={cn(chipVariants({ variant, size }), className)} {...props} />
  )
}
