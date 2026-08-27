import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'
import { humanDate } from '@/lib/taskDates'

/**
 * Поле даты в мобильной строке свойств: видимое значение + прозрачный нативный
 * контрол во всю ячейку.
 *
 * ОС 27.08: «Старт» и «Срок» на iPhone не открывались вовсе, при том что
 * «Колонка» и «Приоритет» в тех же строках работали. Разница — в содержимом: у
 * `<select>` ширину задаёт текст выбранного `<option>`, а пустой
 * `input[type=date]` в общем классе (`appearance-none bg-transparent`, без
 * ширины и фона) на WebKit не показывал ничего и тапаться было не по чему.
 *
 * Точную причину (схлопывание, невидимый плейсхолдер или узкая зона у правого
 * края) воспроизвести в Chromium не удалось — там поле ведёт себя нормально.
 * Поэтому лечим все три разом: зона тапа — вся ячейка, значение рисуем сами,
 * `appearance-none` не используем. `opacity-0` нативность контрола сохраняет:
 * системный пикер открывается по тапу в любую точку строки.
 */
export function MobileDateCell({
  value,
  ariaLabel,
  readOnly,
  onChange,
  className,
  children,
}: {
  value: string
  ariaLabel: string
  readOnly: boolean
  onChange: (value: string) => void
  /** Классы видимого текста — например красный у просроченного срока. */
  className?: string
  /** Сосед слева (бейдж «−N дн»); он ВНЕ зоны тапа. */
  children?: ReactNode
}) {
  const shown = value ? humanDate(value) : '—'
  return (
    <span className="flex min-w-0 flex-1 items-center justify-end gap-2">
      {children}
      {/* flex-1, а не по ширине текста: иначе у пустой даты зона тапа была бы
          22px — ровно по прочерку. Тап должен ловиться на всей свободной
          ширине строки, а бейдж «−N дн» остаётся слева, вне этой зоны. */}
      <span className="relative flex min-h-[46px] min-w-0 flex-1 items-center justify-end">
        <span className={cn('pr-2.5 text-[16px] text-text', !value && 'text-text2', className)}>
          {shown}
        </span>
        {!readOnly && (
          <input
            type="date"
            value={value}
            aria-label={ariaLabel}
            onChange={(e) => onChange(e.target.value)}
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          />
        )}
      </span>
    </span>
  )
}
