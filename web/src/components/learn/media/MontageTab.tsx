import { useQuery } from '@tanstack/react-query'
import { Clapperboard, FilePlus2, MapPin, X } from 'lucide-react'
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Confirm } from '@/components/ui/Confirm'
import { Input } from '@/components/ui/Input'
import { MeterRow } from '@/components/ui/MeterRow'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SegmentGroup } from '@/components/ui/SegmentGroup'
import { Select } from '@/components/ui/Select'
import { Switch } from '@/components/ui/Switch'
import {
  useCancelMediaJob,
  useComposeEstimate,
  useInsertDetails,
  useMediaDetail,
  useStartMediaJob,
  useStoryboard,
  useUpdateStoryboard,
} from '@/hooks/useMediaJobs'
import { hasMediaAvatar, useMe } from '@/hooks/useMe'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import {
  learnApi,
  type DerivedMedia,
  type MediaDetail,
  type MediaStoryboard,
  type StoryboardInsert,
  type StoryboardSegment,
} from '@/lib/learn'
import type { SwapTarget } from '@/lib/lessonVideoNodes'
import {
  activeJob,
  analyzeState,
  composeJobFor,
  composeState,
  failureText,
  formatDuration,
  latestCleaned,
  latestComposed,
  latestJob,
  videoFileProblem,
} from '@/lib/mediaJobs'
import {
  capLabel,
  capPct,
  composeBars,
  composeProgress,
  composeSummary,
  estimateDetail,
  estimateHeadline,
  formatMinutes,
  formatMoney,
  formatRange,
  insertBars,
  insertProblem,
  insertRange,
  moveBoundary,
  payConfirmText,
  pricePerMinute,
  RESOLUTIONS,
  segmentBars,
  segmentCaption,
  segmentTitle,
  setSegmentMode,
  sortInserts,
  speakerHeadline,
  type Bar,
  type Resolution,
} from '@/lib/storyboard'
import { formatClockInput, parseClock } from '@/lib/timeInput'
import { plural } from '@/lib/typography'

import { SwapControls } from './SwapControls'

/**
 * Вкладка «Монтаж» (макеты AvatarSettings / AvatarEstimateStates /
 * AvatarPayConfirm / AvatarResult, ревью 22.10): по ЧИСТОВИКУ — раскадровка
 * (где в кадре спикер → гусь во весь кадр, где показ экрана → кадр из
 * записи), вставки поверх голоса, тумблер гуся, качество, оценка сервера,
 * подтверждение оплаты, ход по отрезкам и результат со свопом в урок.
 * Раскадровка, задание `compose` и результат живут на строке чистовика
 * (`source_media_id` монтажа — чистовик), поэтому деталь здесь — его.
 * Цену и минуты считает только сервер (`/compose/estimate`).
 */
export function MontageTab({
  base,
  nodeMediaId,
  nodeDerived,
  onSwap,
  onRevert,
  onGoCleanup,
}: {
  /** Оригинал — по нему ищется свежий чистовик и считается `usage`. */
  base: MediaDetail
  nodeMediaId: string
  nodeDerived: boolean
  onSwap: (target: SwapTarget) => void
  onRevert: (originalSrc: string | null) => void
  onGoCleanup: () => void
}) {
  const cleaned = latestCleaned(base)
  if (base.status !== 'ready') {
    return <Lead title="Сначала дождитесь конвертации" text="Монтаж собирается по чистовику." />
  }
  if (!cleaned) {
    return (
      <div className="space-y-4">
        <Lead
          title="Сначала соберите чистовик"
          text="Монтаж — гусь вместо спикера и вставки поверх голоса — собирается по чистовику: паузы в нём уже ужаты, звук выровнен, а отрезки со спикером размечаются по готовой картинке."
        />
        <Button size="sm" onClick={onGoCleanup}>
          К чистовику
        </Button>
      </div>
    )
  }
  return (
    <MontageBody
      base={base}
      cleaned={cleaned}
      nodeMediaId={nodeMediaId}
      nodeDerived={nodeDerived}
      onSwap={onSwap}
      onRevert={onRevert}
    />
  )
}

function MontageBody({
  base,
  cleaned,
  nodeMediaId,
  nodeDerived,
  onSwap,
  onRevert,
}: {
  base: MediaDetail
  cleaned: DerivedMedia
  nodeMediaId: string
  nodeDerived: boolean
  onSwap: (target: SwapTarget) => void
  onRevert: (originalSrc: string | null) => void
}) {
  const detail = useMediaDetail(cleaned.id)
  const d = detail.data
  const board = useStoryboard(cleaned.id)
  const aState = analyzeState(d, Boolean(board.data))
  const cState = composeState(d)
  const running = activeJob(d, 'compose')
  const composed = latestComposed(d)
  const start = useStartMediaJob(cleaned.id)
  const cancel = useCancelMediaJob(cleaned.id)
  const [reorder, setReorder] = useState(false)
  const duration = cleaned.duration_sec ?? d?.duration_sec ?? 0

  if (cState === 'running' && running) {
    const progress = composeProgress(running)
    return (
      <div className="space-y-4">
        <Lead
          title={running.status === 'queued' ? 'Ждём очереди…' : 'Собираем монтаж'}
          text="Обычно 5–15 минут на отрезок гуся, вставки — минуты. Шторку можно закрыть — статус будет на блоке видео."
        />
        <div className="h-[6px] w-full overflow-hidden rounded-full bg-surface">
          <div
            className="h-full rounded-full bg-amber transition-[width] duration-500"
            style={{ width: `${progress.pct != null ? Math.max(3, progress.pct) : 3}%` }}
          />
        </div>
        <p className="text-[13px] text-text3">
          {progress.pct != null ? `${progress.pct} % · ` : ''}
          {progress.text}
        </p>
        <Button
          variant="ghost"
          size="sm"
          disabled={cancel.isPending}
          onClick={() => cancel.mutate(running.id)}
        >
          Отменить
        </Button>
        <p className="text-[12px] leading-[1.45] text-text3">
          Отмена после старта возможна, но уже оплаченные отрезки гуся не вернутся.
        </p>
      </div>
    )
  }

  if (cState === 'ready' && composed && !reorder) {
    return (
      <ComposeResult
        base={base}
        cleaned={cleaned}
        composed={composed}
        job={composeJobFor(d)}
        duration={duration}
        inUse={nodeDerived && nodeMediaId === composed.id}
        nodeDerived={nodeDerived}
        onSwap={onSwap}
        onRevert={() => onRevert(base.url)}
        onReorder={() => setReorder(true)}
      />
    )
  }

  if (board.isPending || detail.isPending) {
    return <p className="text-sm text-text3">Загружаем раскадровку…</p>
  }
  if (!board.data) {
    if (aState === 'running') {
      const job = activeJob(d, 'analyze')
      return (
        <Lead
          title={job?.status === 'queued' ? 'Ждём очереди…' : 'Размечаем отрезки'}
          text="Ищем лицо в кадре по секундам — минута-две на получасовую запись. Шторку можно закрыть."
        />
      )
    }
    const failed = aState === 'failed' ? latestJob(d, 'analyze') : null
    return (
      <div className="space-y-4">
        <Lead
          title={failed ? 'Раскадровка не удалась' : 'Раскадровки ещё нет'}
          text={
            failed
              ? `${failureText(failed)}. Повторите; если повторится — напишите администратору.`
              : 'Разметим чистовик: где в кадре человек, где показ экрана. Лицо ищем автоматически, чьё оно — не важно.'
          }
        />
        <Button size="sm" disabled={start.isPending} onClick={() => start.mutate({ kind: 'analyze' })}>
          {failed ? 'Повторить' : 'Разметить отрезки'}
        </Button>
      </div>
    )
  }

  const failed = cState === 'failed' ? latestJob(d, 'compose') : null
  return (
    <StoryboardEditor
      cleaned={cleaned}
      board={board.data}
      duration={duration}
      failed={failed}
      reorder={reorder}
      onBack={composed ? () => setReorder(false) : null}
      onOrder={(resolution) => {
        start.mutate({ kind: 'compose', params: { resolution } })
        setReorder(false)
      }}
      ordering={start.isPending}
    />
  )
}

// ─── Редактор раскадровки ────────────────────────────────────────────────────

const INSERT_MAX_BYTES = 300 * 1024 * 1024
const POLL_MS = 5_000

interface PendingInsert {
  key: string
  name: string
  mediaId: string | null
  status: 'uploading' | 'processing' | 'failed'
  pct: number
  error: string | null
}

let seq = 0

function StoryboardEditor({
  cleaned,
  board,
  duration,
  failed,
  reorder,
  onBack,
  onOrder,
  ordering,
}: {
  cleaned: DerivedMedia
  board: MediaStoryboard
  duration: number
  failed: ReturnType<typeof latestJob>
  reorder: boolean
  onBack: (() => void) | null
  onOrder: (resolution: Resolution) => void
  ordering: boolean
}) {
  const me = useMe()
  const avatarOn = hasMediaAvatar(me.data)
  const isAdmin = me.data?.hub_role === 'admin'
  const canGoose = isAdmin || me.data?.profile?.content_role === 'publisher'
  const update = useUpdateStoryboard(cleaned.id)
  const [resolution, setResolution] = useState<Resolution | undefined>(undefined)
  const estimate = useComposeEstimate(cleaned.id, resolution)
  const est = estimate.data
  const effectiveResolution: Resolution = resolution ?? est?.resolution ?? '720p'
  const [confirm, setConfirm] = useState(false)
  const [boundaries, setBoundaries] = useState(false)
  const player = useRef<HTMLVideoElement | null>(null)
  const transcript = useQuery({
    queryKey: ['learn-media', cleaned.id, 'transcript'],
    queryFn: () => learnApi.mediaTranscript(cleaned.id),
    staleTime: 60_000,
    retry: false,
    meta: { suppressGlobalError: true },
  })

  const save = (patch: Parameters<typeof update.mutate>[0]) => update.mutate(patch)
  const segments = board.segments
  const inserts = sortInserts(board.inserts)
  const gooseOn = board.goose_enabled
  const needsGoose = Boolean(est?.goose_enabled && est.chunks > 0)
  const blocked =
    !est || !est.allowed || ordering || update.isPending || (needsGoose && !canGoose)
  const playerTime = () => Math.round((player.current?.currentTime ?? 0) * 10) / 10

  return (
    <div className="space-y-4">
      {failed ? (
        <Lead
          title="Монтаж не собрался"
          text={`${failureText(failed)}. Поправьте раскадровку или повторите; если повторится — напишите администратору.`}
        />
      ) : (
        <Lead
          title={reorder ? 'Собрать монтаж заново' : 'Монтаж'}
          text="Картинка чистовика собирается заново: там, где в кадре был человек, говорит гусь во весь кадр; поверх голоса можно поставить вставки с процессами магазина; во время показа экрана без вставок остаётся кадр из записи. Голос везде один — из чистовика."
        />
      )}

      <section className="space-y-2">
        <p className="text-[12px] font-semibold uppercase tracking-[0.06em] text-text3">
          Источник · чистовик от {fmtDate(cleaned.created_at)} · {formatDuration(duration)}
        </p>
        {cleaned.url ? (
          <video
            ref={player}
            src={cleaned.url}
            controls
            playsInline
            preload="metadata"
            className="aspect-video w-full rounded-xl bg-black"
          />
        ) : (
          <div className="aspect-video w-full rounded-xl bg-surface" />
        )}
      </section>

      <section className="space-y-2">
        <div>
          <p className="text-[12px] font-semibold uppercase tracking-[0.06em] text-text3">
            Раскадровка
          </p>
          <p className="text-[13px] text-text2">{speakerHeadline(segments, duration)}</p>
        </div>
        <Timeline
          segments={segmentBars(segments, duration)}
          inserts={insertBars(inserts, duration)}
          duration={duration}
        />
        <ol className="divide-y divide-hair rounded-xl border border-hair">
          {segments.map((seg, i) => (
            <SegmentRow
              key={`${seg.s}-${seg.e}`}
              seg={seg}
              caption={segmentCaption(seg, transcript.data)}
              disabled={update.isPending}
              onMode={(mode) => save({ segments: setSegmentMode(segments, i, mode) })}
            />
          ))}
        </ol>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {segments.length > 1 && (
            <button
              type="button"
              className="text-[13px] font-semibold text-amber"
              onClick={() => setBoundaries(true)}
            >
              Поправить границы отрезков…
            </button>
          )}
          <p className="text-[12px] leading-[1.45] text-text3">
            Лицо ищем автоматически, чьё оно — не важно. Короткие отрезки не считаются, стыки
            подтянуты к сменам кадра.
          </p>
        </div>
      </section>

      <InsertsSection
        cleaned={cleaned}
        inserts={inserts}
        duration={duration}
        disabled={update.isPending}
        playerTime={playerTime}
        onChange={(next) => save({ inserts: next })}
      />

      <section className="space-y-3 rounded-xl border border-hair bg-tint p-3">
        <label className="flex items-start gap-2 text-sm text-text2">
          <Switch
            checked={gooseOn}
            disabled={update.isPending || !avatarOn}
            onCheckedChange={(v) => save({ goose_enabled: v })}
          />
          <span>
            Гусь вместо спикера
            <span className="block text-[12px] text-text3">
              {avatarOn
                ? 'Выключите, если нужны только вставки: тогда сборка бесплатна и без Hedra.'
                : 'Гусь на этом сервере выключен — доступны только вставки поверх голоса.'}
            </span>
          </span>
        </label>
        {gooseOn && avatarOn && (
          <div>
            <p className="text-[13px] font-semibold text-text">Качество гуся</p>
            <Select
              value={effectiveResolution}
              className="mt-1"
              onChange={(e) => setResolution(e.target.value as Resolution)}
            >
              {RESOLUTIONS.map((r) => (
                <option key={r} value={r}>
                  {r} · {pricePerMinute(r)}
                </option>
              ))}
            </Select>
            <p className="mt-1 text-[12px] leading-[1.45] text-text3">
              Гусь идёт во весь кадр, поэтому 720p по умолчанию: исходники вебинаров тоже 720p.
            </p>
          </div>
        )}
      </section>

      <EstimateCard
        est={est}
        pending={estimate.isPending}
        error={estimate.isError ? extractErrorDetail(estimate.error) : null}
        isAdmin={isAdmin}
        canGoose={canGoose}
      />

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={blocked}
          onClick={() => (needsGoose ? setConfirm(true) : onOrder(effectiveResolution))}
        >
          <Clapperboard className="h-4 w-4" />{' '}
          {failed ? 'Повторить' : reorder ? 'Собрать заново' : 'Собрать монтаж'}
        </Button>
        {onBack && (
          <Button size="sm" variant="ghost" onClick={onBack}>
            Назад к результату
          </Button>
        )}
      </div>

      {est && (
        <Confirm
          open={confirm}
          onOpenChange={setConfirm}
          title={`Заказать рендер за ≈ ${formatMoney(est.cost_cents)}?`}
          text={payConfirmText(est)}
          confirmLabel={`Заказать за ≈ ${formatMoney(est.cost_cents)}`}
          pending={ordering}
          onConfirm={() => {
            setConfirm(false)
            onOrder(effectiveResolution)
          }}
        />
      )}
      <BoundariesDialog
        open={boundaries}
        onOpenChange={setBoundaries}
        segments={segments}
        duration={duration}
        pending={update.isPending}
        onSave={(next) => {
          save({ segments: next })
          setBoundaries(false)
        }}
      />
    </div>
  )
}

function SegmentRow({
  seg,
  caption,
  disabled,
  onMode,
}: {
  seg: StoryboardSegment
  caption: string | null
  disabled: boolean
  onMode: (mode: 'goose' | 'keep') => void
}) {
  const speaker = seg.kind === 'speaker'
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-text">
          <span className="tabular-nums">{formatRange(seg.s, seg.e)}</span>
          <span className="text-text3"> · {segmentTitle(seg)}</span>
        </p>
        <p className="truncate text-[12px] text-text3">
          {speaker
            ? caption
              ? `«${caption}»`
              : 'подпись появится по субтитрам'
            : 'кадр из записи, голос без изменений'}
        </p>
      </div>
      {speaker && (
        <SegmentGroup
          ariaLabel="Что показывать на отрезке"
          size="sm"
          value={seg.mode ?? 'goose'}
          onChange={(v) => !disabled && onMode(v)}
          options={[
            { value: 'goose', label: 'Гусь' },
            { value: 'keep', label: 'Как есть' },
          ]}
        />
      )}
    </li>
  )
}

/** Полоса: отрезки (амбер — гусь, бледный амбер — спикер «как есть», серый —
 *  показ экрана) и вторая дорожка вставок (бирюза `--sonar`). */
function Timeline({
  segments,
  inserts,
  duration,
}: {
  segments: Bar[]
  inserts: Bar[]
  duration: number
}) {
  return (
    <div className="space-y-1.5">
      <div className="relative h-3 w-full overflow-hidden rounded-full bg-surface">
        {segments.map((b, i) => (
          <span
            key={i}
            title={formatRange(b.s, b.e)}
            className={cn(
              'absolute top-0 h-full',
              b.tone === 'goose' && 'bg-amber',
              b.tone === 'keep' && 'bg-amber/35',
              b.tone === 'screen' && 'bg-text3/25',
            )}
            style={{ left: `${b.left}%`, width: `${b.width}%` }}
          />
        ))}
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-surface">
        {inserts.map((b, i) => (
          <span
            key={i}
            title={formatRange(b.s, b.e)}
            className="absolute top-0 h-full bg-sonar"
            style={{ left: `${b.left}%`, width: `${b.width}%` }}
          />
        ))}
      </div>
      <div className="flex justify-between text-[12px] tabular-nums text-text3">
        <span>0:00</span>
        <span>{formatDuration(duration / 2)}</span>
        <span>{formatDuration(duration)}</span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-text3">
        <span className="flex items-center gap-1.5">
          <i className="h-2 w-2 rounded-full bg-amber" /> спикер в кадре → гусь
        </span>
        <span className="flex items-center gap-1.5">
          <i className="h-2 w-2 rounded-full bg-text3/40" /> показ экрана → кадр из записи
        </span>
        <span className="flex items-center gap-1.5">
          <i className="h-2 w-2 rounded-full bg-sonar" /> вставка поверх голоса
        </span>
      </div>
    </div>
  )
}

function InsertsSection({
  cleaned,
  inserts,
  duration,
  disabled,
  playerTime,
  onChange,
}: {
  cleaned: DerivedMedia
  inserts: StoryboardInsert[]
  duration: number
  disabled: boolean
  playerTime: () => number
  onChange: (next: StoryboardInsert[]) => void
}) {
  const input = useRef<HTMLInputElement | null>(null)
  const [pending, setPending] = useState<PendingInsert[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const details = useInsertDetails(inserts.map((i) => i.media_id))

  const patchPending = (key: string, upd: Partial<PendingInsert>) =>
    setPending((prev) => prev.map((p) => (p.key === key ? { ...p, ...upd } : p)))

  const place = (mediaId: string, length: number, name: string) => {
    const base = inserts.filter((i) => i.media_id !== mediaId)
    const candidates = [playerTime(), ...base.map((i) => Math.min(duration, i.at + i.duration)), 0]
    for (const at of candidates) {
      const next = sortInserts([...base, { media_id: mediaId, at, duration: length }])
      const idx = next.findIndex((i) => i.media_id === mediaId)
      if (insertProblem(next, idx, duration) === null) {
        onChange(next)
        toast.success(`Вставка «${name}» стоит с ${formatDuration(at)}`, {
          description: 'Время можно поправить в строке вставки.',
        })
        return
      }
    }
    toast.error('Не нашли свободного места для вставки', {
      description: 'Уберите или сдвиньте другие вставки и добавьте файл снова.',
    })
  }

  const onPick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const problem = videoFileProblem(file, true, INSERT_MAX_BYTES)
    if (problem) {
      toast.error(`${file.name}: ${problem}`)
      return
    }
    const key = `ins${++seq}`
    setPending((prev) => [
      ...prev,
      { key, name: file.name, mediaId: null, status: 'uploading', pct: 0, error: null },
    ])
    try {
      const media = await learnApi.uploadMedia(file, {
        role: 'insert',
        onProgress: (f) => patchPending(key, { pct: Math.round(f * 100) }),
      })
      if (media.status === 'processing' || media.duration_sec == null) {
        patchPending(key, { mediaId: media.id, status: 'processing', pct: 100 })
      } else {
        setPending((prev) => prev.filter((p) => p.key !== key))
        place(media.id, media.duration_sec, file.name)
      }
    } catch (err) {
      patchPending(key, { status: 'failed', error: extractErrorDetail(err) })
    }
  }

  // Вставка в конвертации (MOV) — ждём готовности, потом ставим на место.
  const processingKey = pending
    .filter((p) => p.status === 'processing' && p.mediaId)
    .map((p) => `${p.key}:${p.mediaId}`)
    .join(',')
  useEffect(() => {
    if (!processingKey) return
    const items = processingKey.split(',').map((x) => x.split(':') as [string, string])
    const tick = async () => {
      for (const [key, id] of items) {
        try {
          const d = await learnApi.mediaDetail(id)
          if (d.status === 'ready' && d.duration_sec != null) {
            setPending((prev) => prev.filter((p) => p.key !== key))
            place(id, d.duration_sec, d.file_name)
          } else if (d.status === 'failed') {
            patchPending(key, { status: 'failed', error: 'Конвертация не удалась' })
          }
        } catch {
          // следующий тик
        }
      }
    }
    const t = setInterval(() => void tick(), POLL_MS)
    return () => clearInterval(t)
    // place/onChange меняются на каждом рендере — ключ достаточен.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processingKey])

  const setAt = (index: number, at: number) => {
    const next = sortInserts(inserts.map((i, k) => (k === index ? { ...i, at } : i)))
    const moved = inserts[index]!
    const idx = next.findIndex((i) => i.media_id === moved.media_id && i.at === at)
    const problem = insertProblem(next, idx, duration)
    if (problem) {
      toast.error(problem)
      return
    }
    onChange(next)
  }

  return (
    <section className="space-y-2">
      <div>
        <p className="text-[12px] font-semibold uppercase tracking-[0.06em] text-text3">
          Вставки поверх голоса
        </p>
        <p className="text-[13px] text-text2">
          кадры с процессами магазина, голос ведущего продолжается
        </p>
      </div>
      {(inserts.length > 0 || pending.length > 0) && (
        <ol className="divide-y divide-hair rounded-xl border border-hair">
          {inserts.map((ins, i) => {
            const info = details[i]?.data
            const draftKey = `${ins.media_id}:${ins.at}`
            const draft = drafts[draftKey] ?? formatClockInput(ins.at)
            return (
              <li key={draftKey} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-semibold text-text">
                    {info?.file_name ?? 'вставка'}
                    <span className="font-normal text-text3">
                      {' '}
                      · {formatDuration(ins.duration)}
                    </span>
                  </p>
                  <p className="text-[12px] text-text3">{insertRange(ins, duration)}</p>
                </div>
                <label className="flex items-center gap-1 text-[12px] text-text3">
                  с
                  <Input
                    value={draft}
                    inputMode="numeric"
                    disabled={disabled}
                    className="h-7 w-[72px] px-2 text-[13px]"
                    onChange={(e) => setDrafts((p) => ({ ...p, [draftKey]: e.target.value }))}
                    onBlur={() => {
                      const parsed = parseClock(draft)
                      setDrafts((p) => {
                        const next = { ...p }
                        delete next[draftKey]
                        return next
                      })
                      if (parsed === null) {
                        toast.error('Время — в виде м:сс или ч:мм:сс')
                        return
                      }
                      if (Math.abs(parsed - ins.at) > 0.05) setAt(i, parsed)
                    }}
                  />
                </label>
                <button
                  type="button"
                  disabled={disabled}
                  title="Поставить на текущее место плеера"
                  className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[12px] font-semibold text-amber hover:bg-glass disabled:opacity-40"
                  onClick={() => setAt(i, playerTime())}
                >
                  <MapPin className="h-3.5 w-3.5" /> Поставить здесь
                </button>
                <button
                  type="button"
                  aria-label="Убрать вставку"
                  disabled={disabled}
                  className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text disabled:opacity-30"
                  onClick={() => onChange(inserts.filter((_, k) => k !== i))}
                >
                  <X className="h-4 w-4" />
                </button>
              </li>
            )
          })}
          {pending.map((p) => (
            <li key={p.key} className="flex items-center gap-3 px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-semibold text-text">{p.name}</p>
                <p className="text-[12px] text-text3">
                  {p.status === 'uploading' && `загрузка ${p.pct} %`}
                  {p.status === 'processing' && 'конвертация в MP4…'}
                  {p.status === 'failed' && <span className="text-red">{p.error}</span>}
                </p>
              </div>
              {p.status === 'failed' && (
                <button
                  type="button"
                  aria-label="Убрать"
                  className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text"
                  onClick={() => setPending((prev) => prev.filter((x) => x.key !== p.key))}
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-hair px-4 py-3 text-sm font-semibold text-amber hover:bg-glass disabled:opacity-50"
      >
        <FilePlus2 className="h-4 w-4" /> Добавить вставку из файла…
      </button>
      <input
        ref={input}
        type="file"
        accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
        hidden
        onChange={(e) => void onPick(e)}
      />
      <p className="text-[12px] leading-[1.45] text-text3">
        Длина вставки = длина ролика, звук вставки не используется. Время — по чистовику
        {cleaned.url ? ': поставьте плеер выше на паузу и нажмите «Поставить здесь»' : ''}. Там,
        где стоит вставка, гусь не нужен, минуты не считаются.
      </p>
    </section>
  )
}

function EstimateCard({
  est,
  pending,
  error,
  isAdmin,
  canGoose,
}: {
  est: ReturnType<typeof useComposeEstimate>['data']
  pending: boolean
  error: string | null
  isAdmin: boolean
  canGoose: boolean
}) {
  if (pending) return <p className="text-[13px] text-text3">Считаем оценку…</p>
  if (!est) {
    return <p className="text-[13px] text-red">{error ?? 'Оценка недоступна'}</p>
  }
  const goose = est.goose_enabled && est.chunks > 0
  return (
    <section className="space-y-2 rounded-xl border border-hair bg-tint p-3">
      <p className="font-display text-[17px] font-bold text-text">{estimateHeadline(est)}</p>
      <p className={cn('text-[13px] leading-[1.45]', est.allowed ? 'text-text2' : 'text-red')}>
        {estimateDetail(est)}
      </p>
      {goose && (
        <MeterRow
          label="Лимит месяца"
          pct={capPct(est)}
          value={capLabel(est)}
          tone={est.allowed ? 'amber' : 'red'}
        />
      )}
      {goose && !est.scene_set && (
        <p className="text-[13px] leading-[1.45] text-text2">
          Нужна картинка 16:9: гусь анфас по центру и фон, который будет виден во весь кадр вместо
          спикера.{' '}
          {isAdmin ? (
            <Link to="/learn/admin?tab=video" className="font-semibold text-amber">
              Открыть «Управление → Видео» →
            </Link>
          ) : (
            'Загружает hub-admin в «Управление → Видео».'
          )}
        </p>
      )}
      {goose && !canGoose && (
        <p className="text-[13px] leading-[1.45] text-red">
          Гусь платный — заказать может publisher или администратор. Выключите гуся, чтобы собрать
          только вставки.
        </p>
      )}
      <p className="text-[12px] leading-[1.45] text-text3">
        {goose
          ? 'Платим только за отрезки со спикером без вставок: списание с кошелька Hedra, перед стартом спросим ещё раз. Вставки бесплатны.'
          : 'Сборка идёт на нашем сервере, Hedra не нужна.'}
      </p>
    </section>
  )
}

function BoundariesDialog({
  open,
  onOpenChange,
  segments,
  duration,
  pending,
  onSave,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  segments: StoryboardSegment[]
  duration: number
  pending: boolean
  onSave: (next: StoryboardSegment[]) => void
}) {
  const [values, setValues] = useState<string[]>([])
  useEffect(() => {
    if (open) setValues(segments.slice(0, -1).map((s) => formatClockInput(s.e)))
  }, [open, segments])
  let next: StoryboardSegment[] = segments
  let problem: string | null = null
  values.forEach((raw, i) => {
    if (problem) return
    const parsed = parseClock(raw)
    const moved = moveBoundary(next, i, parsed ?? Number.NaN)
    if (typeof moved === 'string') problem = `Граница ${i + 1}: ${moved}`
    else next = moved
  })
  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Границы отрезков"
      description={`Время — по чистовику, ${formatDuration(duration)} всего. Вид отрезка не меняется: спикер остаётся спикером, экран — экраном.`}
      desktopWidth={480}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button disabled={Boolean(problem) || pending} onClick={() => onSave(next)}>
            Сохранить
          </Button>
        </>
      }
    >
      <ol className="space-y-2">
        {segments.slice(0, -1).map((seg, i) => (
          <li key={`${seg.s}-${seg.e}`} className="flex items-center gap-3 text-[13px]">
            <span className="min-w-0 flex-1 text-text2">
              {segmentTitle(seg)} → {segmentTitle(segments[i + 1]!)}
            </span>
            <Input
              value={values[i] ?? ''}
              inputMode="numeric"
              className="h-8 w-[88px] px-2 text-[13px]"
              onChange={(e) =>
                setValues((prev) => prev.map((v, k) => (k === i ? e.target.value : v)))
              }
            />
          </li>
        ))}
      </ol>
      {problem && <p className="mt-2 text-[13px] text-red">{problem}</p>}
    </ResponsiveDialog>
  )
}

// ─── Результат ───────────────────────────────────────────────────────────────

function ComposeResult({
  base,
  cleaned,
  composed,
  job,
  duration,
  inUse,
  nodeDerived,
  onSwap,
  onRevert,
  onReorder,
}: {
  base: MediaDetail
  cleaned: DerivedMedia
  composed: DerivedMedia
  job: ReturnType<typeof composeJobFor>
  duration: number
  inUse: boolean
  nodeDerived: boolean
  onSwap: (target: SwapTarget) => void
  onRevert: () => void
  onReorder: () => void
}) {
  const summary = composeSummary(job, duration)
  const bars = composeBars(job, duration)
  return (
    <div className="space-y-4">
      <Lead
        title={inUse ? 'В уроке стоит монтаж' : 'Монтаж готов'}
        text={`Готов ${fmtDate(composed.created_at)}. Чистовик и оригинал остаются — вернуть их можно в любой момент.`}
      />
      <figure className="overflow-hidden rounded-xl border border-hair bg-tint">
        {composed.url ? (
          <video
            src={composed.url}
            controls
            playsInline
            preload="metadata"
            className="aspect-video w-full bg-black"
          />
        ) : (
          <div className="aspect-video w-full bg-surface" />
        )}
        <figcaption className="space-y-1.5 px-3 py-2">
          <div className="relative h-2 w-full overflow-hidden rounded-full bg-surface">
            {bars.map((b, i) => (
              <span
                key={i}
                title={formatRange(b.s, b.e)}
                className={cn(
                  'absolute top-0 h-full',
                  b.tone === 'insert' ? 'bg-sonar' : 'bg-amber',
                )}
                style={{ left: `${b.left}%`, width: `${b.width}%` }}
              />
            ))}
          </div>
          <p className="text-[12px] text-text3">
            Полоса: амбер — говорит гусь, бирюза — вставка поверх голоса. На остальных отрезках
            кадр из чистовика без изменений.
          </p>
        </figcaption>
      </figure>
      {summary && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-xl border border-hair bg-tint p-3 text-sm">
          <dt className="text-text3">Гусь во весь кадр</dt>
          <dd className="text-text">
            {summary.gooseEnabled && summary.gooseChunks > 0
              ? `${plural(summary.gooseChunks, 'отрезок', 'отрезка', 'отрезков')} · ${formatDuration(summary.gooseSeconds)} из ${formatDuration(duration)}`
              : 'выключен'}
          </dd>
          <dt className="text-text3">Вставки поверх голоса</dt>
          <dd className="text-text">
            {summary.inserts > 0
              ? `${summary.inserts} · ${formatDuration(summary.insertSeconds)}`
              : 'нет'}
          </dd>
          <dt className="text-text3">Показ экрана</dt>
          <dd className="text-text">без изменений, голос из чистовика</dd>
          {summary.resolution && (
            <>
              <dt className="text-text3">Качество</dt>
              <dd className="text-text">{summary.resolution}</dd>
            </>
          )}
          <dt className="text-text3">Списано</dt>
          <dd className="text-text">
            {summary.billedSeconds > 0
              ? `${formatMoney(summary.costCents)} · ${formatMinutes(summary.billedSeconds)} лимита`
              : 'бесплатно'}
          </dd>
          <dt className="text-text3">Субтитры</dt>
          <dd className="text-text">
            {cleaned ? 'взяты у чистовика' : '—'}
          </dd>
        </dl>
      )}
      <SwapControls
        base={base}
        target={{ mediaId: composed.id, src: composed.url, derivedKind: 'composed' }}
        inUse={inUse}
        nodeDerived={nodeDerived}
        shorterBy={null}
        onSwap={onSwap}
        onRevert={onRevert}
      >
        <Button size="sm" variant="ghost" onClick={onReorder}>
          Заказать заново
        </Button>
      </SwapControls>
    </div>
  )
}

// ─── Общее ───────────────────────────────────────────────────────────────────

function Lead({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface text-amber">
        <Clapperboard className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-display text-[17px] font-bold text-text">{title}</p>
        <p className="mt-1 text-sm leading-[1.45] text-text2">{text}</p>
      </div>
    </div>
  )
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}
