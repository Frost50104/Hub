import { cn } from '@/lib/cn'

export interface MiniBarPoint {
  key: string
  value: number
  /** title столбика: «3 закрыто». */
  title?: string
}

interface MiniBarChartProps {
  points: MiniBarPoint[]
  /** Высота области столбиков, px. Спека: 104 (моб. 88). */
  height?: number
  /** Подписи под крайними столбиками: «21 июля» / «19 августа». */
  startLabel?: string
  endLabel?: string
  /** Строка справа от заголовка: «Максимум за день — 3». */
  maxLabel?: string
  className?: string
}

/**
 * Столбчатый мини-график flex-`div`'ами (без recharts). Нулевой день —
 * полоса 2px на `--hair`: пустой столбик читался бы как пропуск данных,
 * а не как «ноль закрытий». Цвет ряда — амбер (основной ряд).
 * Значения доступны без hover: `title` на каждом столбике + подписи краёв.
 */
export function MiniBarChart({
  points,
  height = 104,
  startLabel,
  endLabel,
  maxLabel,
  className,
}: MiniBarChartProps) {
  const max = Math.max(0, ...points.map((p) => p.value))
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {maxLabel && (
        <p className="text-right text-[13px] text-text2">{maxLabel}</p>
      )}
      <div className="flex items-end gap-1" style={{ height }} role="img" aria-label="Тренд">
        {points.map((p) => {
          const h = max > 0 && p.value > 0 ? Math.max(4, Math.round((p.value / max) * height)) : 0
          return (
            <span
              key={p.key}
              title={p.title}
              className={cn(
                'flex-1 rounded-t-[3px]',
                h > 0 ? 'bg-amber' : 'h-[2px] bg-hair',
              )}
              style={h > 0 ? { height: h } : undefined}
            />
          )
        })}
      </div>
      {(startLabel || endLabel) && (
        <div className="flex justify-between text-[12px] text-text2">
          <span>{startLabel}</span>
          <span>{endLabel}</span>
        </div>
      )}
    </div>
  )
}
