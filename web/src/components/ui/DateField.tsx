import { Input } from '@/components/ui/Input'
import { SELECT_FIELD_CLASS } from '@/components/ui/Select'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { humanDate } from '@/lib/taskDates'

/**
 * Поле даты формы, которое на iOS не разъезжается.
 *
 * ОС владельца 16.09 (мобильная PWA): в карточке сотрудника «Дата найма»
 * выезжала за правый край и была заметно выше соседних полей, при том что на
 * десктопе тот же `<Input type="date">` укладывается ровно в 36×225, как
 * «Телефон» и «Контур» рядом (замер там же). Причина не в раскладке формы: на
 * WebKit нативный `input[type=date]` несёт собственный внутренний размер и
 * ширину с высотой из CSS слушает плохо.
 *
 * Лечение — то же, что уже работает в строках свойств карточки задачи с 27.08
 * (`ui/MobileDateCell`): значение рисуем САМИ, а нативный контрол растягиваем
 * поверх прозрачным. Тогда коробка — обычный `SELECT_FIELD_CLASS`, то есть
 * ровно как у соседей, а тап по всей её площади открывает системный пикер.
 * `appearance-none` не используем — он на WebKit ломает и отрисовку, и тап
 * (инвариант дизайн-системы).
 *
 * На десктопе остаётся нативное поле: там оно и выглядит верно, и даёт
 * клавиатурный ввод с календарём, терять которые незачем.
 */
export function DateField({
  id,
  value,
  onChange,
  disabled = false,
  className,
  ariaLabel,
}: {
  id?: string
  /** `YYYY-MM-DD` или пустая строка. */
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  className?: string
  ariaLabel?: string
}) {
  const isDesktop = useIsDesktop()

  if (isDesktop) {
    return (
      <Input
        id={id}
        type="date"
        value={value}
        aria-label={ariaLabel}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={className}
      />
    )
  }

  return (
    <span
      className={cn(
        'relative flex items-center overflow-hidden',
        SELECT_FIELD_CLASS,
        disabled && 'opacity-50',
        className,
      )}
    >
      <span className={cn('min-w-0 flex-1 truncate', !value && 'text-text3')}>
        {value ? humanDate(value) : '—'}
      </span>
      {!disabled && (
        // `inset-0` + `opacity-0`: коробку задаёт родитель, а контрол остаётся
        // нативным — системный пикер открывается тапом в любую точку поля.
        <input
          id={id}
          type="date"
          value={value}
          aria-label={ariaLabel}
          onChange={(e) => onChange(e.target.value)}
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        />
      )}
    </span>
  )
}
