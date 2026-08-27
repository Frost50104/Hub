import { useState } from 'react'

import { QueryError } from '@/components/QueryError'
import { MiniBarChart } from '@/components/ui/MiniBarChart'
import { SegmentGroup, type SegmentOption } from '@/components/ui/SegmentGroup'
import { Skeleton } from '@/components/ui/Skeleton'
import { StatTile } from '@/components/ui/StatTile'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMyStats } from '@/hooks/useMyStats'
import { homeStatsView, type HomePeriod } from '@/lib/homeStats'
import { NBSP } from '@/lib/typography'

type PeriodValue = '7' | '30'

const PERIODS: SegmentOption<PeriodValue>[] = [
  { value: '7', label: '7 дней' },
  { value: '30', label: '30 дней' },
]

/**
 * «Ваша статистика» на «Главной» пространства «Задачи».
 *
 * Два числа считаются за выбранный период, два — состояние на сейчас, и это
 * подписано: без уточнения «сейчас» переключатель 7/30 выглядел бы сломанным,
 * когда «просрочено» не меняется.
 *
 * Переключатель в сеть НЕ ходит: ответ несёт оба окна, срез делает
 * `homeStatsView`. Поэтому же период не входит в ключ запроса.
 */
export function UserStatsCard({ className }: { className?: string }) {
  const [period, setPeriod] = useState<HomePeriod>(7)
  const isDesktop = useIsDesktop()
  const { data, isLoading, isError, refetch } = useMyStats()

  const view = data ? homeStatsView(data, period) : null
  // Подпись есть у ВСЕХ четырёх плиток, и не только ради ясности: в ряду
  // `lg:grid-cols-4` grid тянет боксы по высоте, и у плиток без хинта
  // получался бы пустой низ. Заодно снимается вопрос «почему просрочено не
  // меняется от переключателя».
  const windowHint = `за ${period}${NBSP}дней`

  return (
    <section
      className={
        'flex flex-col gap-3.5 rounded-[14px] border border-glass-border bg-tint p-4 ' +
        (className ?? '')
      }
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-body text-[12px] font-bold uppercase tracking-[0.07em] text-text2">
          Ваша статистика
        </h2>
        <SegmentGroup
          options={PERIODS}
          value={String(period) as PeriodValue}
          onChange={(v) => setPeriod(Number(v) as HomePeriod)}
          ariaLabel="Период статистики"
          size={isDesktop ? 'sm' : 'md'}
        />
      </header>

      {isLoading && (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-[74px]" />
          <Skeleton className="h-[104px]" />
        </div>
      )}

      {isError && (
        <QueryError
          title="Не удалось загрузить статистику"
          onRetry={() => void refetch()}
        />
      )}

      {view && (
        <>
          {/* Та же сетка, что у KPI дашборда: на телефоне 2×2, на десктопе в ряд. */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              variant="kpi"
              label="Выполнено"
              value={String(view.completed)}
              tone={view.completed > 0 ? 'success' : 'muted'}
              hint={windowHint}
            />
            <StatTile
              variant="kpi"
              label="Создано"
              value={String(view.created)}
              hint={windowHint}
            />
            <StatTile
              variant="kpi"
              label="В работе"
              value={String(view.open)}
              hint="сейчас"
            />
            <StatTile
              variant="kpi"
              label="Просрочено"
              value={String(view.overdue)}
              tone={view.overdue > 0 ? 'danger' : 'muted'}
              hint="сейчас"
            />
          </div>

          {view.isEmpty ? (
            // Блок не схлопываем: форма экрана не должна прыгать от того,
            // была ли у человека закрытая задача.
            <p className="text-[14px] text-text2">
              За этот период вы ещё ничего не закрыли.
            </p>
          ) : (
            <MiniBarChart
              points={view.points}
              // 104 / 88 — шкала самого компонента (её же держит дашборд).
              height={isDesktop ? 104 : 88}
              // На семи точках `flex-1` раздувает столбик до 44px — вместо
              // динамики получается одна плашка. Тридцати точкам потолок не
              // нужен, они и так узкие.
              maxBarWidth={period === 7 ? 26 : undefined}
              maxLabel={view.maxLabel}
              startLabel={view.startLabel}
              endLabel={view.endLabel}
            />
          )}
        </>
      )}
    </section>
  )
}
