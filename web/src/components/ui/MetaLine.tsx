import { Fragment, type ReactNode } from 'react'

import { cn } from '@/lib/cn'
import { nbsp } from '@/lib/typography'

/**
 * Метастрока вида «v1 · 6,8 МБ · владелец: … · обновлён 14 августа».
 *
 * Ломается ТОЛЬКО по разделителю «·»: каждый фрагмент — отдельный span, а
 * внутри фрагмента стоят неразрывные пробелы. Один текстовый узел рвался бы
 * где попало, и на 360px вниз уезжали одинокие хвосты («1», «240», «4187»).
 *
 * Строковые фрагменты прогоняются через `nbsp()`; готовые узлы (иконка +
 * текст) выводятся как есть — связки в них расставляет вызывающий код.
 */
export function MetaLine({
  items,
  className,
  separator = '·',
}: {
  items: ReactNode[]
  className?: string
  separator?: string
}) {
  const visible = items.filter((item) => item !== null && item !== undefined && item !== false)
  if (visible.length === 0) return null
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5', className)}>
      {visible.map((item, i) => (
        <Fragment key={i}>
          {i > 0 && (
            <span aria-hidden className="text-text3">
              {separator}
            </span>
          )}
          <span className="whitespace-nowrap">
            {typeof item === 'string' ? nbsp(item) : item}
          </span>
        </Fragment>
      ))}
    </span>
  )
}
