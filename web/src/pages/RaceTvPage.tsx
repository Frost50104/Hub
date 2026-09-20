import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

import { RaceBoard } from '@/components/race/RaceBoard'
import { RaceCountdown } from '@/components/race/RaceHeader'
import { RaceTrack } from '@/components/race/RaceTrack'
import { TvFooter } from '@/components/race/tv/TvFooter'
import { TvHeader } from '@/components/race/tv/TvHeader'
import { TvRail } from '@/components/race/tv/TvRail'
import { useElementSize } from '@/hooks/useElementSize'
import { usePublicRace } from '@/hooks/usePublicRace'
import { shouldOfferUpdate } from '@/lib/appVersion'
import { boardState, leagueOptions, tvPageSize, tvRotation } from '@/lib/raceBoard'

const PAGE_MS = 15_000
const TICKS_H = 40
const VERSION_CHECK_MS = 60 * 60_000

/** Высота дорожки от высоты слота: на 1080p — 52px, на низких экранах — 44. */
function laneHeightFor(slotH: number): number {
  return slotH >= 640 ? 52 : 44
}

/**
 * `/p/race/:token` — ТВ-панель вне Shell, без логина, тёмная тема принудительно
 * (сияние и конфетти читаются на тёмном). Раскладка v2 (Claude Design 17.09):
 * шапка с отсчётом и прогрессом дня, трек с пилюлями мест, справа подиум топ-3
 * и места 4–10, футер с ротацией страниц. 63 дорожки не влезают в 1080p —
 * страницы ротируются каждые 15 с; с лигами — страницы общего забега, затем
 * каждой лиги, подиум переключается синхронно. Единственное осознанное
 * самообновление страницы: раз в час сверка версии и reload — на киоске нет
 * ни несохранённой работы, ни человека, который нажмёт «Обновить».
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
  // Всё обязано влезать в один экран без прокрутки: число дорожек и строк
  // лидеров считается от ИЗМЕРЕННОЙ высоты слотов, а не от констант.
  const trackSlot = useRef<HTMLDivElement>(null)
  const trackSize = useElementSize(trackSlot)
  const slotH = trackSize.height || Math.max(300, viewportH - 400)
  const laneH = laneHeightFor(slotH)
  const pageSize = tvPageSize(slotH, laneH, TICKS_H)
  // Правила страниц — в чистой `tvRotation` (общий забег целиком, лига — первая
  // страница, виды без дорожек пропускаются): их проверяет vitest, здесь только
  // подстановка измеренного размера страницы.
  const pages = useMemo(() => tvRotation(options, participants, pageSize), [options, participants, pageSize])
  const [viewportW, setViewportW] = useState(() => (typeof window === 'undefined' ? 1920 : window.innerWidth))
  useEffect(() => {
    const onResize = () => setViewportW(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    if (pages.length <= 1) return
    const id = window.setInterval(() => setPageIdx((i) => (i + 1) % pages.length), PAGE_MS)
    return () => window.clearInterval(id)
  }, [pages.length])

  const safeIdx = Math.min(pageIdx, pages.length - 1)
  const page = pages[safeIdx] ?? { view: 'all', label: 'Общий забег', rows: [] }
  const status = (board.error as { response?: { status?: number } } | null)?.response?.status

  if (!data) {
    return (
      <RaceBoard tv className="min-h-screen bg-bg text-text">
        <div className="flex min-h-screen items-center justify-center p-12" style={{ paddingTop: 'var(--safe-top, 0px)' }}>
          {board.isLoading ? (
            <p className="text-[28px] text-text2">Загружаем гонку…</p>
          ) : (
            <div className="max-w-[820px] text-center">
              <h1 className="font-display text-[44px] font-bold text-text">
                {status === 503 ? 'Публичные ссылки отключены' : 'Ссылка недействительна'}
              </h1>
              <p className="mt-4 text-[24px] text-text2">
                {status === 503
                  ? 'Администратор временно отключил публичные ссылки.'
                  : 'Ссылка отозвана или гонка выключена. Попросите администратора создать новую в «Управлении → Гонка».'}
              </p>
            </div>
          )}
        </div>
      </RaceBoard>
    )
  }

  const state = boardState(data)
  const offlineSince = board.isError && data.as_of ? new Date(data.as_of).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : null
  const waiting = state.kind === 'scheduled' || state.kind === 'between'
  const pageLabel = options.length > 1 ? page.label : null

  return (
    <RaceBoard tv className="h-screen overflow-hidden bg-bg text-text">
      <div
        className="grid h-full grid-rows-[auto_minmax(0,1fr)_auto]"
        style={{
          padding: 'clamp(16px, 2.2vh, 40px) clamp(24px, 2.5vw, 48px)',
          paddingTop: 'calc(var(--safe-top, 0px) + clamp(16px, 2.2vh, 40px))',
          rowGap: 'clamp(12px, 2vh, 28px)',
        }}
      >
        <TvHeader contest={data.contest} race={data.race} state={state} pageLabel={pageLabel} />
        {state.kind === 'no-contest' ? (
          <div className="flex items-center justify-center">
            <p className="text-[32px] text-text2">Гонка ещё не объявлена</p>
          </div>
        ) : (
          <div className="grid min-h-0" style={{ gridTemplateColumns: 'minmax(0,1fr) clamp(380px, 31vw, 600px)', columnGap: 'clamp(16px, 2vw, 40px)' }}>
            <div ref={trackSlot} className="relative min-h-0">
              <div key={`${page.view}-${safeIdx}`} className="race-fade">
                <RaceTrack rows={page.rows} view={page.view} myStoreId={null} selectedId={null} onSelect={() => undefined} tv compactTicks={viewportW < 1600} laneHeight={laneH} />
              </div>
              {waiting && data.race && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                  <div className="glass-solid rounded-2xl border border-hair px-10 py-8 text-center shadow-glass">
                    <p className="uppercase tracking-[0.12em] text-text2" style={{ fontSize: 'var(--race-fs)' }}>
                      {state.kind === 'between' ? `Заезд № ${data.race.seq} стартует через` : 'Заезд стартует через'}
                    </p>
                    <RaceCountdown targetIso={data.race.starts_at} mode="to-start" compact className="mt-2 block leading-none" style={{ fontSize: 'clamp(40px, 3.2vw, 72px)' }} />
                    <p className="mt-3 text-text2" style={{ fontSize: 'var(--race-fs)' }}>Гуси на старте — база = 100 клеток</p>
                  </div>
                </div>
              )}
            </div>
            <div className="min-h-0 overflow-hidden">
              <TvRail participants={participants} view={page.view} />
            </div>
          </div>
        )}
        <TvFooter asOf={data.as_of} nextAt={data.next_refresh_at} pageIdx={safeIdx} pages={pages.length} pageMs={PAGE_MS} offlineSince={offlineSince} />
      </div>
    </RaceBoard>
  )
}
