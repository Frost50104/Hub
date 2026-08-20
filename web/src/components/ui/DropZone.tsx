import { cn } from '@/lib/cn'

/**
 * Одна модель дроп-зоны на весь трекер: пунктир `--amber` 50% + фон 5%.
 * Колонка канбана, папка проектов, ячейка календаря — везде одно и то же,
 * иначе «сюда можно бросить» выглядит в трёх местах тремя способами.
 *
 * Зона всегда несёт рамку (прозрачную в покое): иначе при приёме контент
 * дёргается на 1px.
 */
export function dropZoneClass(active: boolean, extra?: string): string {
  return cn(
    'border border-dashed transition-colors',
    active ? 'border-amber/50 bg-amber/[0.05]' : 'border-transparent',
    extra,
  )
}

/** Чип «Отпустите здесь» — у заголовка группы во время перетаскивания. */
export function DropHint({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-[22px] shrink-0 items-center rounded-md bg-amber px-2 text-[11px] font-bold uppercase tracking-[0.08em] text-on-amber',
        className,
      )}
    >
      Отпустите здесь
    </span>
  )
}
