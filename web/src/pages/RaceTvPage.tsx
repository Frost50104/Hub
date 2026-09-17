import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'

import { RaceBoard } from '@/components/race/RaceBoard'
import { RaceCountdown, RaceFreshness, raceEyebrow } from '@/components/race/RaceHeader'
import { RaceLeaderboard } from '@/components/race/RaceLeaderboard'
import { RaceTrack } from '@/components/race/RaceTrack'
import { usePublicRace } from '@/hooks/usePublicRace'
import { shouldOfferUpdate } from '@/lib/appVersion'
import { dataAgeLabel } from '@/lib/dates'
import { boardState, inView, leagueOptions, tvPages, tvPageSize } from '@/lib/raceBoard'
import { laneOrder } from '@/lib/raceTrack'

const PAGE_MS = 15_000
const LANE_H = 48
const CHROME_H = 300
const VERSION_CHECK_MS = 60 * 60_000

/**
 * `/p/race/:token` — ТВ-панель вне Shell, без логина, тёмная тема принудительно
 * (сияние и конфетти читаются на тёмном). 63 дорожки не влезают в 1080p —
 * страницы ротируются каждые 15 с, справа топ-10; с лигами — страницы общего
 * забега, затем каждой лиги. Единственное осознанное самообновление страницы:
 * раз в час сверка версии и reload — на киоске нет ни несохранённой работы,
 * ни человека, который нажмёт «Обновить».
 */
export function RaceTvPage() {
  const { token } = useParams<{ token: string }>()
  const board = usePublicRace(token)
  const [pageIdx, setPageIdx] = useState(0)
  const [viewportH, setViewportH] = useState(() => (typeof window === 'undefined' ? 1080 : window.innerHeight))

  useEffect(() => {
    document.title = 'Гусиная гонка'
    const tag = document.createElement('meta')
    tag.name = 'referrer'
    tag.content = 'no-referrer'
    document.head.appendChild(tag)
    const onResize = () => setViewportH(window.innerHeight)
    window.addEventListener('resize', onResize)
    return () => {
      document.head.removeChild(tag)
      window.removeEventListener('resize', onResize)
    }
  }, [])

  useEffect(() => {
    const check = async () => {
      if (!navigator.onLine) return
      try {
        const res = await fetch('/version.json', { cache: 'no-store' })
        if (!res.ok) return
        const data = (await res.json()) as { version?: string }
        if (data.version && shouldOfferUpdate(__APP_VERSION__, data.version, null)) window.location.reload()
      } catch {
        // офлайн — следующая проверка через час
      }
    }
    const id = window.setInterval(() => void check(), VERSION_CHECK_MS)
    return () => window.clearInterval(id)
  }, [])

  const data = board.data
  const participants = useMemo(() => data?.participants ?? [], [data])
  const options = useMemo(() => leagueOptions(data?.contest ?? null, participants), [data, participants])
  const pageSize = tvPageSize(viewportH, LANE_H, CHROME_H)
  const pages = useMemo(() => {
    const out: { view: string; label: string; rows: typeof participants }[] = []
    for (const o of options) {
      const rows = laneOrder(participants.filter((p) => inView(p, o.value)))
      for (const chunk of tvPages(rows, pageSize)) out.push({ view: o.value, label: o.label, rows: chunk })
    }
    return out
  }, [options, participants, pageSize])

  useEffect(() => {
    if (pages.length <= 1) return
    const id = window.setInterval(() => setPageIdx((i) => (i + 1) % pages.length), PAGE_MS)
    return () => window.clearInterval(id)
  }, [pages.length])

  const page = pages[Math.min(pageIdx, pages.length - 1)] ?? { view: 'all', label: 'Общий забег', rows: [] }
  const status = (board.error as { response?: { status?: number } } | null)?.response?.status

  if (!data) {
    return (
      <RaceBoard tv className="min-h-screen bg-bg text-text" >
        <div className="flex min-h-screen items-center justify-center p-10" style={{ paddingTop: 'var(--safe-top, 0px)' }}>
          {board.isLoading ? (
            <p className="text-[24px] text-text2">Загружаем гонку…</p>
          ) : (
            <div className="max-w-[720px] text-center">
              <h1 className="font-display text-[40px] font-bold text-text">
                {status === 503 ? 'Публичные ссылки отключены' : 'Ссылка недействительна'}
              </h1>
              <p className="mt-3 text-[20px] text-text2">
                {status === 503 ? 'Администратор временно отключил публичные ссылки.' : 'Ссылка отозвана или гонка выключена. Попросите администратора создать новую в «Управлении → Гонка».'}
              </p>
            </div>
          )}
        </div>
      </RaceBoard>
    )
  }

  const state = boardState(data)
  const countdownTarget = data.race ? (state.kind === 'active' ? data.race.ends_at : data.race.starts_at) : null
  const asOfMs = data.as_of ? new Date(data.as_of).getTime() : null

  return (
    <RaceBoard tv className="min-h-screen bg-bg text-text">
      <div className="grid min-h-screen grid-rows-[auto_minmax(0,1fr)] gap-6 p-10" style={{ paddingTop: 'calc(var(--safe-top, 0px) + 40px)' }}>
        <header className="flex items-end justify-between gap-8">
          <div className="min-w-0">
            <p className="text-text2" style={{ fontSize: 'var(--race-fs)' }}>
              {raceEyebrow(data.race, data.contest)}
              {pages.length > 1 && ` · ${page.label} · дорожка ${Math.min(pageIdx, pages.length - 1) + 1}/${pages.length}`}
            </p>
            <h1 className="font-display font-bold leading-[1.1] text-text" style={{ fontSize: 'clamp(28px, 2.4vw, 52px)' }}>
              Гусиная гонка{data.contest ? ` · ${data.contest.title}` : ''}
            </h1>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            {countdownTarget && (
              <RaceCountdown targetIso={countdownTarget} mode={state.kind === 'active' ? 'to-end' : 'to-start'} compact className="leading-none" style={{ fontSize: "clamp(36px, 3.2vw, 72px)" }} />
            )}
            {board.isError && asOfMs && (
              <p className="text-text2" style={{ fontSize: 'var(--race-fs)' }}>Нет связи — {dataAgeLabel(asOfMs)?.toLowerCase()}</p>
            )}
            <RaceFreshness asOf={data.as_of} nextAt={data.next_refresh_at} />
          </div>
        </header>
        {state.kind === 'no-contest' ? (
          <div className="flex items-center justify-center">
            <p className="text-[28px] text-text2">Гонка ещё не объявлена</p>
          </div>
        ) : (
          <div className="grid min-h-0 gap-8 grid-cols-[minmax(0,1fr)_520px]">
            <div key={`${page.view}-${pageIdx}`} className="race-fade min-h-0">
              <RaceTrack rows={page.rows} view={page.view} myStoreId={null} selectedId={null} onSelect={() => undefined} tv />
            </div>
            <div className="min-h-0 overflow-hidden">
              <RaceLeaderboard participants={participants} view={page.view} myStoreId={null} limit={10} tv />
            </div>
          </div>
        )}
      </div>
    </RaceBoard>
  )
}
