import { useQuery } from '@tanstack/react-query'
import { Download, RefreshCw, Subtitles } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/Button'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SegmentGroup } from '@/components/ui/SegmentGroup'
import { useCancelMediaJob, useMediaDetail, useStartMediaJob } from '@/hooks/useMediaJobs'
import { learnApi, type MediaDetail } from '@/lib/learn'
import type { SwapTarget } from '@/lib/lessonVideoNodes'
import { activeJob, failureText, formatDuration, latestJob, transcribeState } from '@/lib/mediaJobs'

import { CleanupTab } from './CleanupTab'
import { MontageTab } from './MontageTab'

/**
 * Шторка инструментов видеоблока (макеты «Чистовик видео урока», холст
 * GbzNFbfcNCftQtcyyiwPFq): шторка ниже `lg`, модалка 760 на десктопе. Три
 * вкладки — «Субтитры» (инкремент 5), «Чистовик» (6), «Монтаж» (7).
 * Состояние файла делит с видеоблоком ключ `['learn-media', id]`. «База» —
 * всегда ОРИГИНАЛ: у ноды с чистовиком это его источник, у ноды с монтажом —
 * источник чистовика (`source_media_id` монтажа указывает на чистовик).
 */
export type MediaToolsTab = 'subtitles' | 'cleanup' | 'montage'
type Tab = MediaToolsTab

export function MediaToolsSheet({
  mediaId,
  nodeDerived,
  open,
  onOpenChange,
  onSwap,
  onRevert,
  initialTab = 'subtitles',
}: {
  mediaId: string
  /** Нода урока уже показывает производную (чистовик/монтаж). */
  nodeDerived: boolean
  open: boolean
  onOpenChange: (v: boolean) => void
  onSwap: (target: SwapTarget) => void
  onRevert: (originalSrc: string | null) => void
  initialTab?: Tab
}) {
  const detail = useMediaDetail(mediaId, open)
  const d = detail.data
  // Чистовик и монтаж заказываются и показываются по ОРИГИНАЛУ: у ноды с
  // чистовиком «база» — его источник, у ноды с монтажом — источник чистовика.
  const midId = d?.variant === 'composed' ? d.source_media_id : null
  const mid = useMediaDetail(midId, open && Boolean(midId))
  const baseId =
    d?.variant === 'cleaned'
      ? d.source_media_id
      : d?.variant === 'composed'
        ? (mid.data?.source_media_id ?? null)
        : mediaId
  const base = useMediaDetail(baseId, open && Boolean(baseId) && baseId !== mediaId)
  const baseDetail = baseId === mediaId ? d : base.data
  const [tab, setTab] = useState<Tab>(initialTab)
  const title = d
    ? `${d.file_name}${d.duration_sec ? ` · ${formatDuration(d.duration_sec)}` : ''}`
    : 'Видео'
  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description="Субтитры, чистовик и монтаж"
      desktopWidth={760}
      dismissLabel="Закрыть"
    >
      <div className="space-y-4">
        <SegmentGroup
          ariaLabel="Инструменты видео"
          size="md"
          value={tab}
          onChange={setTab}
          options={[
            { value: 'subtitles', label: 'Субтитры' },
            { value: 'cleanup', label: 'Чистовик' },
            { value: 'montage', label: 'Монтаж' },
          ]}
        />
        {detail.isPending && <p className="text-sm text-text3">Загружаем…</p>}
        {detail.isError && (
          <p className="text-sm text-red">
            Не удалось получить состояние файла — попробуйте ещё раз.
          </p>
        )}
        {d && tab === 'subtitles' && <SubtitlesTab detail={d} />}
        {d && tab === 'cleanup' && baseDetail && (
          <CleanupTab
            base={baseDetail}
            nodeMediaId={mediaId}
            nodeDerived={nodeDerived}
            onSwap={onSwap}
            onRevert={onRevert}
          />
        )}
        {d && tab === 'montage' && baseDetail && (
          <MontageTab
            base={baseDetail}
            nodeMediaId={mediaId}
            nodeDerived={nodeDerived}
            onSwap={onSwap}
            onRevert={onRevert}
            onGoCleanup={() => setTab('cleanup')}
          />
        )}
        {d && (tab === 'cleanup' || tab === 'montage') && !baseDetail && (
          <p className="text-sm text-text3">Загружаем…</p>
        )}
      </div>
    </ResponsiveDialog>
  )
}

function fmtDate(iso: string): string {
  const dt = new Date(iso)
  return dt.toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function Header({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface text-amber">
        <Subtitles className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-display text-[17px] font-bold text-text">{title}</p>
        {children}
      </div>
    </div>
  )
}

export function SubtitlesTab({ detail }: { detail: MediaDetail }) {
  const state = transcribeState(detail)
  const start = useStartMediaJob(detail.id)
  const cancel = useCancelMediaJob(detail.id)
  const running = activeJob(detail, 'transcribe')
  const last = latestJob(detail, 'transcribe')
  const transcript = useQuery({
    queryKey: ['learn-media', detail.id, 'transcript'],
    queryFn: () => learnApi.mediaTranscript(detail.id),
    enabled: state === 'ready',
    staleTime: 60_000,
    retry: false,
    meta: { suppressGlobalError: true },
  })

  if (detail.status !== 'ready') {
    return (
      <Header title="Сначала дождитесь конвертации">
        <p className="mt-1 text-sm leading-[1.45] text-text2">
          Субтитры делаются по готовому MP4 — расшифровка начнётся сама, когда файл будет готов.
        </p>
      </Header>
    )
  }

  if (state === 'unavailable') {
    return (
      <Header title="Расшифровка здесь не подключена">
        <p className="mt-1 text-sm leading-[1.45] text-text2">
          На этом сервере нет службы распознавания речи. Субтитры, чистовик и гусь появятся, когда
          администратор её подключит. Видео в уроке работает как обычно.
        </p>
      </Header>
    )
  }

  if (state === 'running') {
    const pct = running?.result.progress?.pct
    const stage = running?.result.progress?.stage
    return (
      <div className="space-y-4">
        <Header title={running?.status === 'queued' ? 'Ждём очереди…' : 'Расшифровываем…'}>
          <p className="mt-1 text-sm leading-[1.45] text-text2">
            Около 12 минут на получасовую запись. Шторку можно закрыть — статус будет на блоке.
          </p>
        </Header>
        <div className="h-[6px] w-full overflow-hidden rounded-full bg-surface">
          <div
            className="h-full rounded-full bg-amber transition-[width] duration-500"
            style={{
              width: `${typeof pct === 'number' ? Math.max(3, pct) : 3}%`,
            }}
          />
        </div>
        <p className="text-[13px] text-text3">
          {typeof pct === 'number' ? `${pct} %` : 'запуск'}
          {stage === 'audio' && ' · извлекаем звук'}
          {stage === 'silence' && ' · ищем паузы'}
          {stage === 'transcribe' && ' · распознаём'}
        </p>
        {running && (
          <Button
            variant="ghost"
            size="sm"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate(running.id)}
          >
            Отменить
          </Button>
        )}
      </div>
    )
  }

  if (state === 'ready' && detail.transcript) {
    const t = detail.transcript
    const segments = transcript.data?.segments.slice(0, 6) ?? []
    return (
      <div className="space-y-4">
        <Header title="Субтитры готовы">
          <p className="mt-1 text-sm text-text2">
            {fmtDate(t.updated_at)} · {t.language === 'ru' ? 'русский' : t.language} ·{' '}
            {t.chars.toLocaleString('ru-RU')} знаков
          </p>
        </Header>
        {segments.length > 0 && (
          <ol className="space-y-1.5 rounded-xl border border-hair bg-tint p-3">
            {segments.map((seg) => (
              <li key={seg.s} className="flex gap-3 text-sm leading-[1.45]">
                <span className="w-10 shrink-0 tabular-nums text-text3">
                  {formatDuration(seg.s)}
                </span>
                <span className="text-text">{seg.t}</span>
              </li>
            ))}
          </ol>
        )}
        <p className="text-[13px] leading-[1.45] text-text3">
          В плеере включены по умолчанию, сотрудник может выключить. Распознано {t.model} с
          глоссарием тенанта; текст попал в поиск и к ассистенту.
        </p>
        <div className="flex flex-wrap gap-2">
          {detail.subtitle_url && (
            <a
              href={detail.subtitle_url}
              download
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-hair px-3 text-[13px] font-semibold text-text hover:bg-glass"
            >
              <Download className="h-4 w-4" /> Скачать .vtt
            </a>
          )}
          <Button
            variant="ghost"
            size="sm"
            disabled={start.isPending}
            onClick={() => start.mutate('transcribe')}
          >
            <RefreshCw className="h-4 w-4" /> Переделать
          </Button>
        </div>
      </div>
    )
  }

  if (state === 'failed') {
    return (
      <div className="space-y-4">
        <Header title="Расшифровка не удалась">
          <p className="mt-1 text-sm leading-[1.45] text-text2">
            {failureText(last)}. Это не ваша ошибка: повторите, а если повторится — напишите
            администратору.
          </p>
          {last && (
            <p className="mt-1 text-[13px] text-text3">
              {last.finished_at ? fmtDate(last.finished_at) : ''} · попытка {last.attempts} из 2
              {last.error ? ` · код ${last.error.split(':')[0]}` : ''}
            </p>
          )}
        </Header>
        <Button size="sm" disabled={start.isPending} onClick={() => start.mutate('transcribe')}>
          <RefreshCw className="h-4 w-4" /> Повторить
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <Header title="Субтитров пока нет">
        <p className="mt-1 text-sm leading-[1.45] text-text2">
          Расшифруем запись на сервере: субтитры появятся в плеере, текст попадёт в поиск и к
          ассистенту.
        </p>
        <p className="mt-1 text-[13px] leading-[1.45] text-text3">
          Около 12 минут на получасовую запись. Правка текста субтитров — позже, пока только
          автоматическая расшифровка.
        </p>
      </Header>
      <Button size="sm" disabled={start.isPending} onClick={() => start.mutate('transcribe')}>
        Запустить расшифровку
      </Button>
    </div>
  )
}
