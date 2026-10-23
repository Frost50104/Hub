import { useQuery } from '@tanstack/react-query'
import { Scissors } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Confirm } from '@/components/ui/Confirm'
import { SegmentGroup } from '@/components/ui/SegmentGroup'
import { Select } from '@/components/ui/Select'
import { Switch } from '@/components/ui/Switch'
import { useCancelMediaJob, useStartMediaJob } from '@/hooks/useMediaJobs'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { learnApi, type DerivedMedia, type MediaDetail } from '@/lib/learn'
import {
  activeJob,
  cleanupJobFor,
  cleanupPauses,
  cleanupState,
  cleanupStats,
  failureText,
  formatDelta,
  formatDuration,
  latestCleaned,
  latestJob,
  mapOriginalTime,
  swapImpactText,
  type PauseRow,
} from '@/lib/mediaJobs'
import type { SwapTarget } from '@/lib/lessonVideoNodes'

import { useMediaToolsContext } from './MediaToolsContext'

/**
 * Вкладка «Чистовик» (макеты CleanupSettings / Progress / CleanupResult /
 * SwapConfirm): заказ по оригиналу (`base`), результат — свежий чистовик из
 * `derived`. Нода урока может уже показывать чистовик (`nodeDerived`): тогда
 * вместо «Заменить» — «Вернуть оригинал». Своп — только на клиенте
 * (`onSwap`/`onRevert` меняют атрибуты ноды), вступает в силу после
 * сохранения урока.
 */
export function CleanupTab({
  base,
  nodeMediaId,
  nodeDerived,
  onSwap,
  onRevert,
}: {
  /** Оригинал (для чистовика — его источник). */
  base: MediaDetail
  nodeMediaId: string
  nodeDerived: boolean
  onSwap: (target: SwapTarget) => void
  onRevert: (originalSrc: string | null) => void
}) {
  const state = cleanupState(base)
  const start = useStartMediaJob(base.id)
  const cancel = useCancelMediaJob(base.id)
  const running = activeJob(base, 'cleanup')
  const cleaned = latestCleaned(base)
  const job = cleanupJobFor(base)
  const [pause, setPause] = useState<'0' | '1' | '1.5' | '2'>('1.5')
  const [denoise, setDenoise] = useState(true)
  const [loudnorm, setLoudnorm] = useState(true)
  const [rebuild, setRebuild] = useState(false)

  const order = () => {
    start.mutate({
      kind: 'cleanup',
      params: {
        min_pause_sec: Number(pause),
        denoise: denoise ? 'afftdn' : 'none',
        loudnorm,
      },
    })
    setRebuild(false)
  }

  if (base.status !== 'ready') {
    return (
      <Lead title="Сначала дождитесь конвертации" text="Чистовик собирается по готовому MP4." />
    )
  }
  if (!base.capabilities.cleanup && state === 'none') {
    return (
      <Lead
        title="Сначала дождитесь расшифровки"
        text="Паузы ищутся по звуку и тексту вместе — так тихая речь не режется. Когда субтитры будут готовы, чистовик станет доступен."
      />
    )
  }

  if (state === 'running' && running) {
    const pct = running.result.progress?.pct
    const stage = running.result.progress?.stage
    return (
      <div className="space-y-4">
        <Lead
          title={running.status === 'queued' ? 'Ждём очереди…' : 'Собираем чистовик'}
          text="Обычно 10–20 минут на получасовую запись. Шторку можно закрыть — статус будет на блоке видео."
        />
        <div className="h-[6px] w-full overflow-hidden rounded-full bg-surface">
          <div
            className="h-full rounded-full bg-amber transition-[width] duration-500"
            style={{ width: `${typeof pct === 'number' ? Math.max(3, pct) : 3}%` }}
          />
        </div>
        <p className="text-[13px] text-text3">
          {typeof pct === 'number' ? `${pct} %` : 'запуск'}
          {stage === 'audio' && ' · извлекаем звук'}
          {stage === 'silence' && ' · ищем паузы'}
          {stage === 'loudness' && ' · измеряем громкость'}
          {stage === 'render' && ' · рендер видео и склейка звука'}
        </p>
        <Button
          variant="ghost"
          size="sm"
          disabled={cancel.isPending}
          onClick={() => cancel.mutate(running.id)}
        >
          Отменить
        </Button>
      </div>
    )
  }

  if (state === 'ready' && cleaned && !rebuild) {
    return (
      <CleanupResult
        base={base}
        cleaned={cleaned}
        stats={cleanupStats(job)}
        pauses={cleanupPauses(job)}
        inUse={nodeDerived && nodeMediaId === cleaned.id}
        nodeDerived={nodeDerived}
        onSwap={onSwap}
        onRevert={() => onRevert(base.url)}
        onRebuild={() => setRebuild(true)}
      />
    )
  }

  const failed = state === 'failed' ? latestJob(base, 'cleanup') : null
  return (
    <div className="space-y-4">
      {failed ? (
        <Lead
          title="Чистовик не собрался"
          text={`${failureText(failed)}. Повторите; если повторится — напишите администратору.`}
        />
      ) : (
        <Lead
          title={rebuild ? 'Собрать заново с другими настройками' : 'Чистовика ещё нет'}
          text={
            rebuild
              ? 'Новый чистовик появится рядом со старым, старый не удаляется.'
              : 'Соберём копию записи: ужмём длинные паузы, уберём шум и выровняем громкость. Оригинал останется, заменить видео в уроке можно будет после просмотра.'
          }
        />
      )}
      <div className="space-y-3 rounded-xl border border-hair bg-tint p-3">
        <div>
          <p className="text-[13px] font-semibold text-text">Паузы</p>
          <Select
            value={pause}
            onChange={(e) => setPause(e.target.value as typeof pause)}
            className="mt-1"
          >
            <option value="1">Ужимать паузы длиннее 1,0 с</option>
            <option value="1.5">Ужимать паузы длиннее 1,5 с</option>
            <option value="2">Ужимать паузы длиннее 2,0 с</option>
            <option value="0">Не трогать паузы</option>
          </Select>
          <p className="mt-1 text-[12px] leading-[1.45] text-text3">
            Паузу не вырезаем, а укорачиваем до ~0,7 с: речь не слипается, а показ экрана не
            дёргается.
          </p>
        </div>
        <label className="flex items-start gap-2 text-sm text-text2">
          <Switch checked={denoise} onCheckedChange={setDenoise} />
          <span>
            Убрать шум
            <span className="block text-[12px] text-text3">
              Фон, шипение, гул вентилятора. Голос не трогаем.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-sm text-text2">
          <Switch checked={loudnorm} onCheckedChange={setLoudnorm} />
          <span>
            Выровнять громкость
            <span className="block text-[12px] text-text3">
              Единый уровень на всей записи, пики не режутся.
            </span>
          </span>
        </label>
      </div>
      <p className="text-[12px] leading-[1.45] text-text3">
        Обычно 10–20 минут на получасовую запись. Шторку можно закрыть — статус будет на блоке
        видео.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={start.isPending} onClick={order}>
          <Scissors className="h-4 w-4" />{' '}
          {failed ? 'Повторить' : rebuild ? 'Собрать заново' : 'Собрать чистовик'}
        </Button>
        {rebuild && (
          <Button size="sm" variant="ghost" onClick={() => setRebuild(false)}>
            Назад к результату
          </Button>
        )}
      </div>
    </div>
  )
}

function Lead({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface text-amber">
        <Scissors className="h-5 w-5" />
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

function CleanupResult({
  base,
  cleaned,
  stats,
  pauses,
  inUse,
  nodeDerived,
  onSwap,
  onRevert,
  onRebuild,
}: {
  base: MediaDetail
  cleaned: DerivedMedia
  stats: ReturnType<typeof cleanupStats>
  pauses: PauseRow[]
  inUse: boolean
  nodeDerived: boolean
  onSwap: (target: SwapTarget) => void
  onRevert: () => void
  onRebuild: () => void
}) {
  const { lessonId, lessonStatus } = useMediaToolsContext()
  const isDesktop = useIsDesktop()
  const [showAll, setShowAll] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const usage = useQuery({
    queryKey: ['learn-media', base.id, 'usage'],
    queryFn: () => learnApi.mediaUsage(base.id),
    enabled: confirm && lessonStatus === 'published',
    staleTime: 30_000,
    retry: false,
    meta: { suppressGlobalError: true },
  })
  const shorter = stats ? stats.source_sec - stats.output_sec : null
  const visible = showAll ? pauses : pauses.slice(0, 6)
  const inThisLesson = usage.data?.lessons.find((l) => l.lesson_id === lessonId)
  const others = usage.data ? usage.data.lessons.filter((l) => l.lesson_id !== lessonId).length : 0

  const doSwap = () => {
    onSwap({ mediaId: cleaned.id, src: cleaned.url, derivedKind: 'cleaned' })
    setConfirm(false)
    toast.success('Видео заменено — сохраните урок', {
      description: 'Оригинал остался, вернуть его можно в любой момент из этой шторки.',
    })
  }
  const swapClick = () => {
    if (lessonStatus === 'published') setConfirm(true)
    else doSwap()
  }

  return (
    <div className="space-y-4">
      <Lead
        title={inUse ? 'В уроке стоит чистовик' : 'Чистовик готов'}
        text={`Готов ${fmtDate(cleaned.created_at)}. Оригинал останется — вернуть его можно в любой момент.`}
      />
      <BeforeAfter base={base} cleaned={cleaned} pauses={pauses} desktop={isDesktop} />
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-xl border border-hair bg-tint p-3 text-sm">
        <dt className="text-text3">Длительность</dt>
        <dd className="text-text">
          {formatDuration(base.duration_sec)} → {formatDuration(cleaned.duration_sec)}
          {shorter != null && shorter > 0.5 && (
            <span className="text-text3"> · короче на {formatDelta(shorter)}</span>
          )}
        </dd>
        <dt className="text-text3">Паузы</dt>
        <dd className="text-text">
          {stats ? `${stats.pauses} ужато` : '—'}
          {stats && stats.removed_sec > 0 && (
            <span className="text-text3"> · {formatDelta(-stats.removed_sec)}</span>
          )}
        </dd>
        <dt className="text-text3">Звук</dt>
        <dd className="text-text">Шум и громкость — по настройкам заказа</dd>
      </dl>
      {pauses.length > 0 && (
        <div className="space-y-1">
          <p className="text-[12px] font-semibold uppercase tracking-[0.06em] text-text3">
            Ужатые паузы · время в чистовике · было → стало
          </p>
          <ol className="max-h-56 space-y-1 overflow-y-auto rounded-xl border border-hair p-2">
            {visible.map((p) => (
              <li key={`${p.source_at}`} className="flex items-baseline gap-3 text-[13px]">
                <span className="w-12 shrink-0 tabular-nums text-text3">
                  {formatDuration(p.at)}
                </span>
                <span className="min-w-0 flex-1 truncate text-text2">{p.context ?? 'пауза'}</span>
                <span className="shrink-0 tabular-nums text-text">
                  {p.was_sec.toFixed(1).replace('.', ',')} →{' '}
                  {p.now_sec.toFixed(1).replace('.', ',')} с
                </span>
              </li>
            ))}
          </ol>
          {pauses.length > 6 && (
            <button
              type="button"
              className="text-[13px] font-semibold text-amber"
              onClick={() => setShowAll((v) => !v)}
            >
              {showAll ? 'Свернуть' : `Показать все ${pauses.length}`}
            </button>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {inUse ? (
          <Button size="sm" variant="secondary" onClick={onRevert}>
            Вернуть оригинал
          </Button>
        ) : (
          <Button size="sm" onClick={swapClick} disabled={nodeDerived && !inUse}>
            Заменить в уроке
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onRebuild}>
          Собрать заново
        </Button>
      </div>
      <Confirm
        open={confirm}
        onOpenChange={setConfirm}
        title="Заменить видео в опубликованном уроке?"
        text={
          usage.isPending
            ? 'Считаем, сколько человек сейчас проходят урок…'
            : swapImpactText(inThisLesson?.in_progress ?? 0, others, shorter)
        }
        confirmLabel="Заменить"
        pending={usage.isPending}
        onConfirm={doSwap}
      />
    </div>
  )
}

/** Десктоп — два плеера рядом (play одного ставит второй на паузу); телефон —
 *  один плеер и переключатель, позиция переносится через `mapOriginalTime`. */
function BeforeAfter({
  base,
  cleaned,
  pauses,
  desktop,
}: {
  base: MediaDetail
  cleaned: DerivedMedia
  pauses: PauseRow[]
  desktop: boolean
}) {
  const [which, setWhich] = useState<'original' | 'cleaned'>('cleaned')
  const a = useRef<HTMLVideoElement | null>(null)
  const b = useRef<HTMLVideoElement | null>(null)
  const single = useRef<HTMLVideoElement | null>(null)
  if (desktop) {
    return (
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: 'Оригинал', url: base.url, dur: base.duration_sec, ref: a, other: b },
          { label: 'Чистовик', url: cleaned.url, dur: cleaned.duration_sec, ref: b, other: a },
        ].map((v) => (
          <figure key={v.label} className="overflow-hidden rounded-xl border border-hair bg-tint">
            {v.url ? (
              <video
                ref={v.ref}
                src={v.url}
                controls
                playsInline
                preload="metadata"
                className="aspect-video w-full bg-black"
                onPlay={() => v.other.current?.pause()}
              />
            ) : (
              <div className="aspect-video w-full bg-surface" />
            )}
            <figcaption className="flex justify-between px-3 py-2 text-[13px] text-text2">
              <span>{v.label}</span>
              <span className="tabular-nums">{formatDuration(v.dur)}</span>
            </figcaption>
          </figure>
        ))}
      </div>
    )
  }
  const switchTo = (next: 'original' | 'cleaned') => {
    const el = single.current
    const t = el?.currentTime ?? 0
    setWhich(next)
    requestAnimationFrame(() => {
      const target = single.current
      if (!target) return
      target.currentTime = next === 'cleaned' ? mapOriginalTime(t, pauses) : t
    })
  }
  const url = which === 'cleaned' ? cleaned.url : base.url
  return (
    <div className="space-y-2">
      <SegmentGroup
        ariaLabel="Оригинал или чистовик"
        size="md"
        fullWidth
        value={which}
        onChange={switchTo}
        options={[
          { value: 'original', label: `Оригинал · ${formatDuration(base.duration_sec)}` },
          { value: 'cleaned', label: `Чистовик · ${formatDuration(cleaned.duration_sec)}` },
        ]}
      />
      {url ? (
        <video
          key={which}
          ref={single}
          src={url}
          controls
          playsInline
          preload="metadata"
          className="aspect-video w-full rounded-xl bg-black"
        />
      ) : (
        <div className="aspect-video w-full rounded-xl bg-surface" />
      )}
      <p className="text-[12px] text-text3">Переключение держит место в записи.</p>
    </div>
  )
}
