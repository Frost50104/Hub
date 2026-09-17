import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { QueryError } from '@/components/QueryError'
import { LeagueSegment } from '@/components/race/LeagueSegment'
import { RaceBoard } from '@/components/race/RaceBoard'
import { RaceChart } from '@/components/race/RaceChart'
import { RaceEmptyState } from '@/components/race/RaceEmptyState'
import { RaceCountdown, RaceHeader } from '@/components/race/RaceHeader'
import { RaceHistory } from '@/components/race/RaceHistory'
import { RaceLeaderboard } from '@/components/race/RaceLeaderboard'
import { RaceStandings } from '@/components/race/RaceStandings'
import { RaceTrack } from '@/components/race/RaceTrack'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useMe } from '@/hooks/useMe'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useRaceBoard, useRaceChart, useRaceHistory } from '@/hooks/useRace'
import { boardState, inView, leagueOptions, resolveRaceParams, resolveView, setRaceParams } from '@/lib/raceBoard'
import { dataAgeLabel } from '@/lib/dates'

/**
 * `/learn/race` — трек, лидеры, история, зачёт, график. Состояние вида —
 * в URL (`league`, `race`, `store`), выбранный гусь и «показать все» — локально.
 * Клетки, проценты и места считает сервер; экран только раскладывает.
 */
export function LearnRacePage() {
  const isDesktop = useIsDesktop()
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const board = useRaceBoard()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const data = board.data
  const myStoreId = data?.my_store_id ?? null
  const participants = useMemo(() => data?.participants ?? [], [data])
  const urlParams = resolveRaceParams(params)
  const view = resolveView(urlParams.league, data?.contest ?? null, participants, myStoreId)
  const rows = useMemo(() => participants.filter((p) => inView(p, view)), [participants, view])

  const races = data?.contest?.races ?? []
  const selectableRaces = races.filter((r) => r.status !== 'scheduled')
  const chartRaceId = urlParams.race && selectableRaces.some((r) => r.id === urlParams.race) ? urlParams.race : data?.race && data.race.status !== 'scheduled' ? data.race.id : selectableRaces[selectableRaces.length - 1]?.id ?? null
  const historyStoreId = urlParams.store ?? myStoreId ?? participants[0]?.store_id ?? null
  const history = useRaceHistory(historyStoreId, data?.contest?.id ?? null)
  const chart = useRaceChart(chartRaceId, historyStoreId)

  useEffect(() => {
    if (selectedId && !rows.some((p) => p.store_id === selectedId)) setSelectedId(null)
  }, [rows, selectedId])

  if (board.isLoading && !data) {
    return (
      <div className="mx-auto max-w-[1200px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
        <SkeletonRows rows={8} rowClassName="h-9" />
      </div>
    )
  }
  if (!data) {
    return (
      <div className="mx-auto max-w-[1200px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
        <QueryError onRetry={() => void board.refetch()} />
      </div>
    )
  }

  const state = boardState(data)
  const isAdmin = me.data?.hub_role === 'admin'
  const stale = board.isError && data
  const asOfMs = data.as_of ? new Date(data.as_of).getTime() : null

  return (
    <RaceBoard>
      <div className="mx-auto max-w-[1200px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
        <RaceHeader contest={data.contest} race={data.race} state={state} asOf={data.as_of} nextAt={data.next_refresh_at} isDesktop={isDesktop} />
        {stale && (
          <p className="mt-3 rounded-lg border border-red/30 bg-red/5 px-3 py-2 text-[13px] text-text">
            Не удалось обновить данные{asOfMs ? ` — ${dataAgeLabel(asOfMs)?.toLowerCase() ?? ''}` : ''}.
          </p>
        )}

        {state.kind === 'no-contest' ? (
          <div className="mt-5">
            <RaceEmptyState state={state} isAdmin={isAdmin} />
          </div>
        ) : (
          <>
            <div className="mt-4 lg:mt-5">
              <LeagueSegment
                options={leagueOptions(data.contest, participants)}
                value={view}
                onChange={(v) => setParams(setRaceParams(params, { league: v }), { replace: true })}
                isDesktop={isDesktop}
              />
            </div>
            {!isDesktop && state.kind === 'active' && (
              <div
                className="sticky z-10 -mx-5 mt-3 flex items-center justify-between bg-bg-alt px-5 py-2 text-[12px] text-text2"
                style={{ top: 'var(--safe-top, 0px)' }}
              >
                <span>Заезд № {state.race.seq}</span>
                <RaceCountdown targetIso={state.race.ends_at} mode="to-end" compact className="text-[16px]" />
              </div>
            )}
            {state.kind === 'finished' && (
              <div className="mt-5">
                <RaceStandings standings={data.standings} myStoreId={myStoreId} />
              </div>
            )}
            <div className="mt-3">
              <RaceTrack
                rows={rows}
                view={view}
                myStoreId={myStoreId}
                selectedId={selectedId}
                onSelect={setSelectedId}
                scrollInside={isDesktop && rows.length > 24}
              />
            </div>
            {state.kind === 'scheduled' ? (
              <p className="mt-4 text-[14px] text-text2">
                Гуси на старте. Заезд начнётся по расписанию — база задана у{' '}
                {participants.filter((p) => !p.needs_baseline).length} из {participants.length} точек.
              </p>
            ) : (
              <>
                <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_460px]">
                  <RaceLeaderboard participants={participants} view={view} myStoreId={myStoreId} />
                  <RaceChart
                    races={races}
                    raceId={chartRaceId}
                    onRaceChange={(id) => setParams(setRaceParams(params, { race: id }), { replace: true })}
                    chart={chart.data}
                    loading={chart.isLoading}
                    height={isDesktop ? 240 : 200}
                  />
                </div>
                <div className="mt-6 grid gap-6 lg:grid-cols-2">
                  <RaceHistory
                    participants={participants}
                    storeId={historyStoreId}
                    onStoreChange={(id) => setParams(setRaceParams(params, { store: id }), { replace: true })}
                    rows={history.data?.races}
                    loading={history.isLoading}
                  />
                  {state.kind !== 'finished' && <RaceStandings standings={data.standings} myStoreId={myStoreId} />}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </RaceBoard>
  )
}
