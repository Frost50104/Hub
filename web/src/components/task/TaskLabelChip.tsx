import { Chip } from '@/components/ui/Chip'
import { cn } from '@/lib/cn'
import { labelChipColors } from '@/lib/labelChip'
import { type Label } from '@/lib/labels'

/**
 * Метка — плотная заливка в её собственный цвет, а не точка 6px рядом с
 * текстом: цвет метки — её единственный смысл, и раньше на него отводилось
 * шесть пикселей. Краска считается по контрасту (см. lib/labelChip.ts).
 */
export function TaskLabelChip({
  label,
  size,
  className,
}: {
  label: Label
  size?: 'sm' | 'md'
  className?: string
}) {
  const colors = labelChipColors(label.color)
  return (
    <Chip
      variant="custom"
      size={size}
      style={colors}
      // Единственный сжимаемый элемент строки контекста: усечётся сам, а
      // счётчик подзадач и «+N» останутся целы.
      className={cn('min-w-0 truncate', className)}
      title={label.name}
    >
      {label.name}
    </Chip>
  )
}
