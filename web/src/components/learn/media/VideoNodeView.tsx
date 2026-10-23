import { NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from '@tiptap/react'
import { useEffect, useState } from 'react'

import { LessonVideo } from '@/components/learn/rich/lessonNodes'
import { Chip } from '@/components/ui/Chip'
import { useMediaDetail } from '@/hooks/useMediaJobs'
import { cn } from '@/lib/cn'
import { revertedVideoAttrs, swappedVideoAttrs, type SwapTarget } from '@/lib/lessonVideoNodes'
import {
  activeJob,
  blockStatus,
  cleanupState,
  formatDelta,
  formatDuration,
  latestCleaned,
  latestComposed,
  transcribeChip,
} from '@/lib/mediaJobs'

import { MediaToolsSheet, type MediaToolsTab } from './MediaToolsSheet'

/**
 * Видеоблок редактора при включённом конвейере (0066): живое состояние файла
 * (конвертация, сборка, расшифровка) и кнопка «Субтитры и чистовик…».
 * Подключается ТОЛЬКО при `me.features.media_pipeline` — `useEditor`
 * собирается один раз, поэтому `LessonEditor` ждёт `me` до рендера редактора.
 * Старая статическая разметка `LessonVideo.renderHTML` остаётся для
 * выключенного конвейера.
 */
function VideoNodeViewInner({ node, selected, updateAttributes }: NodeViewProps) {
  const mediaId = typeof node.attrs.mediaId === 'string' ? node.attrs.mediaId : null
  const detail = useMediaDetail(mediaId)
  const d = detail.data
  const [sheetOpen, setSheetOpen] = useState(false)

  // Файл стал готов, а в контенте `src` ещё пустой (вставлен в processing):
  // подставляем адрес один раз, чтобы превью в редакторе заиграло без
  // пересохранения. Сервер всё равно переподписывает `src` при отдаче.
  useEffect(() => {
    if (d?.status === 'ready' && d.url && !node.attrs.src) updateAttributes({ src: d.url })
  }, [d?.status, d?.url, node.attrs.src, updateAttributes])

  const status = blockStatus(d)
  const chip = transcribeChip(d)
  const nodeDerived = node.attrs.derivedKind === 'cleaned' || node.attrs.derivedKind === 'composed'
  const cleaned = !nodeDerived ? latestCleaned(d) : null
  const cleanupRunning = cleanupState(d) === 'running'
  // Задания чистовика (в том числе `compose`) видны и у оригинала — сервер
  // собирает их по производным; готовый монтаж лежит в `derived` ЧИСТОВИКА.
  const composeRunning = activeJob(d, 'compose') !== null
  const composed = d?.variant === 'cleaned' ? latestComposed(d) : null
  const initialTab: MediaToolsTab =
    node.attrs.derivedKind === 'composed' || composed || composeRunning
      ? 'montage'
      : cleaned || nodeDerived
        ? 'cleanup'
        : 'subtitles'
  const onSwap = (target: SwapTarget) => updateAttributes(swappedVideoAttrs(node.attrs, target))
  const onRevert = (originalSrc: string | null) => {
    const next = revertedVideoAttrs(node.attrs, originalSrc)
    if (next) updateAttributes(next)
  }
  const badges: string[] = ['Видео']
  if (node.attrs.derivedKind === 'cleaned') badges.push('чистовик')
  if (node.attrs.derivedKind === 'composed') badges.push('монтаж')
  if (node.attrs.requireFullWatch) badges.push('обязательный досмотр')
  if (node.attrs.disableSeek) badges.push('без перемотки')
  const src = (d?.url ?? (typeof node.attrs.src === 'string' ? node.attrs.src : null)) || null

  return (
    <NodeViewWrapper
      data-lesson-video=""
      className={cn(
        'my-2 rounded-lg border p-1',
        selected ? 'border-amber' : 'border-glass-border',
      )}
      contentEditable={false}
    >
      {status.kind === 'processing' || status.kind === 'failed' || !src ? (
        <div
          className={cn(
            'flex aspect-video w-full flex-col items-center justify-center gap-1.5 rounded bg-surface px-4 text-center',
            status.kind === 'failed' && 'border border-red/40',
          )}
        >
          <p
            className={cn(
              'text-[15px] font-semibold',
              status.kind === 'failed' ? 'text-red' : 'text-text',
            )}
          >
            {status.kind === 'processing'
              ? status.label
              : status.kind === 'failed'
                ? status.label
                : 'Видео'}
            {status.kind === 'processing' && status.pct != null && status.pct > 0
              ? ` ${status.pct} %`
              : ''}
          </p>
          <p className="text-[13px] leading-[1.45] text-text2">
            {status.kind === 'processing'
              ? 'Урок можно сохранять, видео появится здесь само. Опубликовать урок получится после конвертации.'
              : status.kind === 'failed'
                ? 'Удалите блок и загрузите файл заново; если повторится — напишите администратору.'
                : 'Файл ещё не готов.'}
          </p>
          {d && (
            <p className="text-[12px] text-text3">
              {d.file_name}
              {d.size_bytes ? ` · ${Math.round(d.size_bytes / 1024 / 1024)} МБ` : ''}
            </p>
          )}
        </div>
      ) : (
        <video
          src={src}
          controls
          playsInline
          preload="metadata"
          className="w-full rounded bg-black"
        />
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-1 pt-1">
        <p className="text-xs text-text3">
          {badges.join(' · ')}
          {d?.duration_sec ? ` · ${formatDuration(d.duration_sec)}` : ''}
        </p>
        {chip && (
          <Chip
            variant={chip.tone === 'danger' ? 'danger' : chip.tone === 'ok' ? 'outline' : 'neutral'}
            className={cn(
              chip.tone === 'ok' && 'border-green-deep/50 text-green-deep',
              chip.tone === 'progress' && 'text-amber',
            )}
          >
            {chip.text}
          </Chip>
        )}
        {cleanupRunning && (
          <Chip variant="neutral" className="text-amber">
            Собираем чистовик…
          </Chip>
        )}
        {cleaned && d?.duration_sec && cleaned.duration_sec != null && (
          <Chip variant="outline" className="border-green-deep/50 text-green-deep">
            Чистовик готов
            {d.duration_sec - cleaned.duration_sec > 0.5
              ? ` · ${formatDelta(-(d.duration_sec - cleaned.duration_sec))}`
              : ''}
          </Chip>
        )}
        {composeRunning && (
          <Chip variant="neutral" className="text-amber">
            Собираем монтаж…
          </Chip>
        )}
        {composed && node.attrs.derivedKind !== 'composed' && (
          <Chip variant="outline" className="border-green-deep/50 text-green-deep">
            Монтаж готов
          </Chip>
        )}

        {d && d.status === 'ready' && (
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setSheetOpen(true)}
            className="ml-auto rounded px-1.5 py-1 text-xs font-semibold text-amber hover:bg-glass"
          >
            Субтитры и чистовик…
          </button>
        )}
      </div>
      {mediaId && sheetOpen && (
        <MediaToolsSheet
          mediaId={mediaId}
          nodeDerived={nodeDerived}
          open={sheetOpen}
          onOpenChange={setSheetOpen}
          onSwap={onSwap}
          onRevert={onRevert}
          initialTab={initialTab}
        />
      )}
    </NodeViewWrapper>
  )
}

/** Та же нода `video`, но с React-представлением в редакторе. */
export const LessonVideoWithView = LessonVideo.extend({
  addNodeView() {
    return ReactNodeViewRenderer(VideoNodeViewInner)
  },
})
