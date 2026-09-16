import { useQuery } from '@tanstack/react-query'
import { Download, Search } from 'lucide-react'
import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { FilterChip } from '@/components/ui/FilterChip'
import { Input } from '@/components/ui/Input'
import { SearchableSelect } from '@/components/ui/SearchableSelect'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { StatTile } from '@/components/ui/StatTile'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useOrgSnapshot } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { learnApi } from '@/lib/learn'
import {
  barSegmented,
  clearProgressParams,
  type EmployeeProgressRow,
  filterProgressRows,
  hasActiveFilters,
  mandatoryShort,
  orgLine,
  PROGRESS_BUCKETS,
  PROGRESS_SORTS,
  progressAria,
  progressBucket,
  progressCaption,
  progressCounts,
  progressMetaLine,
  progressPct,
  progressPillClass,
  progressPillLabel,
  resolveProgressFilters,
  resolveProgressSort,
  setProgressParams,
  sortProgressRows,
} from '@/lib/learnProgress'
import { shortDate } from '@/lib/taskDates'

import { useAdminEmbedded } from './adminEmbed'
import { EmployeeProgressDialog } from './EmployeeProgressDialog'

/**
 * «Управление → Прогресс сотрудников»: кто сколько обязательных курсов прошёл.
 *
 * Экран отвечает на «кто отстаёт», и его раскладка продиктована замерами прода
 * (16.09): из 315 активных карточек 134 человека ни разу не заходили в Hub, а
 * из 181 зашедшего 136 не начали ни одного обязательного курса. Поэтому:
 *
 * * распределение показывают KPI-плитки и чипы-фасетки С ЧИСЛАМИ — увидеть
 *   картину надо ДО первой строки, иначе экран выглядит как 250 одинаковых
 *   нулей;
 * * по умолчанию НИЧЕГО не отфильтровано: преднастроенная фасетка — та же
 *   тихая обрезка выдачи, из-за которой однажды «потерялся» Пётр Попов;
 * * сортировка «отстающие сверху» сравнивает ДОЛЮ и уводит в хвост тех, кому
 *   проходить нечего.
 *
 * Раскраска — по спеке Claude Design: пройденное ПРИГЛУШАЕТСЯ, а не
 * подсвечивается (иначе 23 завершивших конкурируют за внимание со 136 не
 * начавшими), красный зарезервирован за просрочкой и ошибкой, нейтральный
 * бейдж — `surface` + `text2`.
 *
 * Состояние фильтров живёт в адресе: экран существует ради фразы «вот эти
 * 12 человек в Галерее, разберись», и ссылка обязана их открывать. Плюс
 * `LearnAdminPage` монтирует вкладку с `key={active}` — локальный `useState`
 * умер бы при переходе в «Аналитику» и обратно.
 */
export function LearnProgressPage() {
  const isDesktop = useIsDesktop()
  const embedded = useAdminEmbedded()
  const [params, setParams] = useSearchParams()

  const urlFilters = resolveProgressFilters(params)
  const sort = resolveProgressSort(params)
  // Дебаунс гасит пересортировку всего набора на каждую букву.
  const q = useDebouncedValue(urlFilters.q, 300)
  const filters = useMemo(() => ({ ...urlFilters, q }), [urlFilters, q])

  const data = useQuery({
    queryKey: ['learn-employee-progress'],
    queryFn: () => learnApi.employeeProgress({}),
    staleTime: 60_000,
  })
  const org = useOrgSnapshot()

  const openId = params.get('person')
  const rows = useMemo(() => data.data?.items ?? [], [data.data])
  const counts = useMemo(() => progressCounts(rows), [rows])
  const visible = useMemo(
    () => sortProgressRows(filterProgressRows(rows, filters), sort),
    [rows, filters, sort],
  )

  const patch = (next: Parameters<typeof setProgressParams>[1]) =>
    setParams((prev) => setProgressParams(prev, next), { replace: true })

  const storeOptions = useMemo(
    () =>
      (org.data?.stores ?? [])
        .filter((s) => !s.archived_at)
        .map((s) => ({ value: s.id, label: s.name })),
    [org.data],
  )

  const exportParams = {
    ...(filters.q ? { q: filters.q } : {}),
    ...(filters.storeId ? { store_id: filters.storeId } : {}),
    ...(filters.positionId ? { position_id: filters.positionId } : {}),
  }

  return (
    <div className={embedded ? undefined : 'mx-auto max-w-4xl'}>
      {!isDesktop && !embedded && (
        <MobilePageHeader eyebrow="Обучение" title="Прогресс сотрудников" />
      )}
      <div className={embedded ? 'flex flex-col gap-5' : 'flex flex-col gap-5 p-4 lg:p-8'}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          {isDesktop && !embedded && (
            <h1 className="font-display text-2xl font-bold text-text">
              Прогресс обучения
            </h1>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {data.data && (
              <span className="text-[13px] text-text2">
                {data.data.scope === 'all' ? 'срез: вся сеть' : 'срез: мои точки'} ·
                считает сервер
              </span>
            )}
            <Button
              variant="secondary"
              className="bg-transparent"
              title="Выгрузка учитывает фильтры экрана"
              onClick={() => void learnApi.downloadAnalyticsCsv(exportParams)}
            >
              <Download className="h-4 w-4" /> Выгрузить CSV
            </Button>
          </div>
        </div>

        {data.isLoading && <SkeletonRows rows={6} />}
        {data.isError && <QueryError onRetry={() => void data.refetch()} />}

        {data.data && data.data.scope === 'stores' && rows.length === 0 && (
          <EmptyState
            layout="card"
            title="За вами не закреплено ни одной точки"
            text="Пока точки не назначены, прогресс показывать не по кому — попросите администратора закрепить точки."
          />
        )}

        {data.data && rows.length > 0 && (
          <>
            <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
              <StatTile variant="kpi" label="Людей в срезе" value={String(counts.total)} />
              <StatTile
                variant="kpi"
                label="Завершили всё"
                value={String(counts.done)}
                tone="success"
              />
              {/* Не `danger`: красная плашка на большинстве выборки обесценила
                  бы красный на всём экране. Тревогу несёт само число. */}
              <StatTile variant="kpi" label="Не начинали" value={String(counts.none)} />
              <StatTile
                variant="kpi"
                label="Не заходили в Hub"
                value={String(counts.neverActive)}
                tone="muted"
                hint="прогресса быть не может"
              />
            </div>

            <div className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none] lg:mx-0 lg:flex-wrap lg:px-0">
              <FilterChip
                size={isDesktop ? 'md' : 'lg'}
                active={filters.bucket === null}
                onClick={() => patch({ bucket: null })}
              >
                Все {counts.total}
              </FilterChip>
              {PROGRESS_BUCKETS.map((b) => {
                const n =
                  b.key === 'done'
                    ? counts.done
                    : b.key === 'partial'
                      ? counts.partial
                      : b.key === 'none'
                        ? counts.none
                        : counts.nothingAssigned
                return (
                  <FilterChip
                    key={b.key}
                    size={isDesktop ? 'md' : 'lg'}
                    active={filters.bucket === b.key}
                    onClick={() => patch({ bucket: filters.bucket === b.key ? null : b.key })}
                  >
                    {b.label} {n}
                  </FilterChip>
                )
              })}
              <FilterChip
                size={isDesktop ? 'md' : 'lg'}
                active={filters.linkedOnly}
                onClick={() => patch({ linkedOnly: !filters.linkedOnly })}
              >
                Только с учётной записью
              </FilterChip>
            </div>

            <div className="flex flex-wrap gap-2">
              <div className="relative min-w-[200px] flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-text3" />
                <Input
                  className="pl-8"
                  placeholder="Поиск по имени, почте, точке…"
                  value={urlFilters.q}
                  onChange={(e) => patch({ q: e.target.value })}
                />
              </div>
              <SearchableSelect
                className="w-[200px]"
                sheetTitle="Точка"
                placeholder="Все точки"
                clearLabel="Все точки"
                value={filters.storeId}
                onChange={(value) => patch({ storeId: value })}
                options={storeOptions}
              />
              <Select
                className="w-[180px]"
                aria-label="Должность"
                value={filters.positionId ?? ''}
                onChange={(e) => patch({ positionId: e.target.value || null })}
              >
                <option value="">Все должности</option>
                {(org.data?.positions ?? [])
                  .filter((p) => !p.archived_at)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
              </Select>
              <Select
                className="w-[190px]"
                aria-label="Сортировка"
                value={sort}
                onChange={(e) =>
                  patch({ sort: e.target.value as (typeof PROGRESS_SORTS)[number]['key'] })
                }
              >
                {PROGRESS_SORTS.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </div>

            <p className="text-xs text-text3">
              {progressCaption({
                matched: visible.length,
                loaded: rows.length,
                total: data.data.total,
                filtered: hasActiveFilters(filters),
              })}
            </p>

            {visible.length === 0 ? (
              <EmptyState
                layout="card"
                title="Никого не нашли"
                text="Под эти фильтры не попал ни один сотрудник."
                cta="Сбросить фильтры"
                onCta={() =>
                  setParams((prev) => clearProgressParams(prev), { replace: true })
                }
              />
            ) : (
              <div className="overflow-hidden rounded-[14px] border border-hair bg-tint">
                <div className="hidden grid-cols-[minmax(0,1fr)_188px_172px_108px] items-center gap-3 bg-surface px-3.5 py-2.5 text-[12px] font-bold uppercase tracking-[0.07em] text-text2 lg:grid">
                  <span>Сотрудник</span>
                  <span>Точка · должность</span>
                  <span>Обязательные</span>
                  <span>Состояние</span>
                </div>
                {visible.map((row, i) => (
                  <ProgressRow
                    key={row.profile_id}
                    row={row}
                    first={i === 0}
                    onOpen={() => setPerson(setParams, row.profile_id)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {openId && (
        <EmployeeProgressDialog
          profileId={openId}
          onClose={() => setPerson(setParams, null)}
        />
      )}
    </div>
  )
}

/** `person` — не фильтр, поэтому живёт мимо `setProgressParams`. */
function setPerson(
  setParams: ReturnType<typeof useSearchParams>[1],
  profileId: string | null,
) {
  setParams(
    (prev) => {
      const next = new URLSearchParams(prev)
      if (profileId) next.set('person', profileId)
      else next.delete('person')
      return next
    },
    { replace: true },
  )
}

function ProgressRow({
  row,
  first,
  onOpen,
}: {
  row: EmployeeProgressRow
  first: boolean
  onOpen: () => void
}) {
  const bucket = progressBucket(row)
  const total = row.mandatory_total
  const done = Math.min(row.mandatory_done, total)
  const meta = orgLine(row)

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={progressAria(row)}
      className={cn(
        'flex w-full flex-wrap items-center gap-x-2.5 gap-y-1 px-3.5 py-[11px] text-left',
        'lg:grid lg:grid-cols-[minmax(0,1fr)_188px_172px_108px] lg:items-center lg:gap-x-3 lg:gap-y-1',
        first ? 'lg:border-t lg:border-hair' : 'border-t border-hair',
        'cursor-pointer transition-colors hover:bg-glass',
      )}
    >
      <span className="order-1 min-w-0 flex-1 lg:order-none lg:flex-none">
        <span
          className="block truncate text-[15px] font-semibold leading-[1.3] text-text lg:text-[16px]"
          title={row.full_name}
        >
          {row.full_name}
        </span>
        <span className="mt-[3px] block truncate text-[13px] text-text2 lg:hidden">
          {meta}
        </span>
      </span>

      <span className="hidden min-w-0 truncate text-[14px] text-text2 lg:block" title={meta}>
        {meta}
      </span>

      <span className="order-3 flex basis-full items-center gap-2 lg:order-none lg:basis-auto">
        <span className="shrink-0 text-[13px] text-text2 lg:hidden">Обязательные</span>
        <MandatoryBar done={done} total={total} />
        <span className="shrink-0 whitespace-nowrap font-display text-[14px] font-bold tabular-nums text-text">
          {mandatoryShort(done, total)}
        </span>
      </span>

      <span className="order-2 shrink-0 lg:order-none">
        <span
          className={cn(
            'inline-flex h-[22px] items-center rounded-md px-2 text-[12px] font-semibold',
            progressPillClass(bucket),
          )}
        >
          {progressPillLabel(bucket)}
        </span>
      </span>

      <span className="order-4 basis-full text-[13px] leading-[1.4] text-text2 lg:order-none lg:col-span-4">
        {progressMetaLine(row)}
        {row.last_activity_at && ` · был ${shortDate(row.last_activity_at)}`}
      </span>
    </button>
  )
}

/**
 * Сегмент на курс, пока знаменатель обозрим, иначе сплошная полоса.
 *
 * Заливка — `--green` (спека прямо оставляет зелёный «для полос прогресса»),
 * амбер зарезервирован за значением «обязательный» и украшением не служит.
 */
function MandatoryBar({ done, total }: { done: number; total: number }) {
  if (total <= 0) {
    return <span className="block h-1.5 min-w-[64px] flex-1 rounded-[3px] bg-surface" aria-hidden />
  }
  if (barSegmented(total)) {
    return (
      <span className="flex h-1.5 min-w-[64px] flex-1 gap-[3px]" aria-hidden>
        {Array.from({ length: total }, (_, k) => (
          <span
            key={k}
            className={cn('h-1.5 flex-1 rounded-[2px]', k < done ? 'bg-green' : 'bg-surface')}
          />
        ))}
      </span>
    )
  }
  return (
    <span className="block h-1.5 min-w-[64px] flex-1 overflow-hidden rounded-[3px] bg-surface" aria-hidden>
      <span
        className="block h-1.5 rounded-[3px] bg-green"
        style={{ width: `${progressPct(done, total)}%` }}
      />
    </span>
  )
}
