import { ClipboardList, ExternalLink, FileText } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  RichRenderer,
  type ExtraNodeRenderers,
  type RichNode,
} from '@/components/learn/rich/RichRenderer'
import { type LessonContent } from '@/lib/learn'

import { CheckQuestion } from './CheckQuestion'
import { ImageLightbox, type LightboxImage } from './ImageLightbox'
import { Skeleton } from '@/components/ui/Skeleton'
import { VideoPlayer } from './VideoPlayer'

// LessonRenderer грузится НЕ-lazy из LearnLessonPage — pdf.js обязан
// оставаться отдельным lazy-чанком (вне PWA-precache), иначе вклеится
// в чанк страницы урока и прекешится каждому сотруднику.
const PdfViewer = lazy(() => import('./PdfViewer'))

/**
 * Рендер контента урока (Ф3a) = RichRenderer + доменные ноды. БЕЗ ProseMirror.
 * media-ноды приходят с сервера уже с подписанным attrs.src; correct у
 * checkQuestion вырезан (проверка ответа — только на сервере).
 *
 * Все картинки кликабельны по умолчанию → ImageLightbox (attr `lightbox`
 * у figure-ноды остаётся неиспользуемым — кликабельность не опциональна).
 */

function str(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

export function LessonRenderer({
  lesson,
  onBlockAnswered,
  onVideoCoverage,
  className,
}: {
  lesson: LessonContent
  onBlockAnswered?: (blockId: string, correct: boolean) => void
  onVideoCoverage?: (mediaId: string, coverage: number) => void
  className?: string
}) {
  const answers = lesson.block_state.answers ?? {}
  const videoState = lesson.block_state.video ?? {}
  const [lightbox, setLightbox] = useState<{
    images: LightboxImage[]
    index: number
  } | null>(null)

  const extraNodes: ExtraNodeRenderers = {
    figure: (node: RichNode, index: number) => {
      const src = str(node.attrs?.src)
      const caption = str(node.attrs?.caption)
      if (!src) return null
      return (
        <figure key={index} className="my-3">
          <button
            type="button"
            onClick={() => setLightbox({ images: [{ src, caption }], index: 0 })}
            className="block cursor-zoom-in rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            aria-label="Открыть изображение на весь экран"
          >
            <img
              src={src}
              alt={caption || 'Иллюстрация'}
              loading="lazy"
              className="max-h-[480px] w-auto max-w-full rounded-lg border border-glass-border"
            />
          </button>
          {caption && (
            <figcaption className="mt-1 text-xs text-text3">{caption}</figcaption>
          )}
        </figure>
      )
    },

    gallery: (node: RichNode, index: number) => {
      const items = Array.isArray(node.attrs?.items)
        ? (node.attrs.items as { src?: string; caption?: string }[])
        : []
      const visible = items.filter((it) => it.src)
      if (!visible.length) return null
      const lightboxImages: LightboxImage[] = visible.map((it, i) => ({
        src: it.src as string,
        caption: it.caption || `Шаг ${i + 1}`,
      }))
      return (
        <div key={index} className="my-3 flex gap-2 overflow-x-auto pb-1">
          {visible.map((item, i) => (
            <figure key={i} className="w-44 shrink-0 sm:w-56">
              <button
                type="button"
                onClick={() => setLightbox({ images: lightboxImages, index: i })}
                className="block w-full cursor-zoom-in rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                aria-label={`Открыть изображение ${i + 1} на весь экран`}
              >
                <img
                  src={item.src}
                  alt={item.caption || `Шаг ${i + 1}`}
                  loading="lazy"
                  className="h-32 w-full rounded-lg border border-glass-border object-cover sm:h-40"
                />
              </button>
              <figcaption className="mt-1 text-xs text-text3">
                {item.caption || `Шаг ${i + 1}`}
              </figcaption>
            </figure>
          ))}
        </div>
      )
    },

    video: (node: RichNode, index: number) => {
      const src = str(node.attrs?.src)
      const mediaId = str(node.attrs?.mediaId)
      if (!src || !mediaId) return null
      const saved = videoState[mediaId]
      return (
        <VideoPlayer
          key={`${mediaId}-${index}`}
          lessonId={lesson.id}
          mediaId={mediaId}
          src={src}
          requireFullWatch={Boolean(node.attrs?.requireFullWatch)}
          disableSeek={Boolean(node.attrs?.disableSeek)}
          initialIntervals={saved?.intervals ?? []}
          onCoverageChange={
            onVideoCoverage ? (c) => onVideoCoverage(mediaId, c) : undefined
          }
        />
      )
    },

    pdfEmbed: (node: RichNode, index: number) => {
      const src = str(node.attrs?.src)
      if (!src) return null
      const forbidDownload = Boolean(node.attrs?.forbidDownload)
      // pdf.js вместо iframe (Android Chrome не рендерит PDF во
      // встраиваниях); подписанный URL работает без Bearer.
      return (
        <div key={index} className="my-3 space-y-2">
          <Suspense fallback={<Skeleton className="h-[70vh] w-full rounded-lg" />}>
            <PdfViewer
              src={src}
              title="Документ PDF"
              fallbackHref={!forbidDownload ? src : undefined}
            />
          </Suspense>
          {!forbidDownload && (
            <a
              href={src}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm text-amber transition-opacity hover:opacity-80"
            >
              <FileText className="h-4 w-4" />
              Открыть в новой вкладке
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      )
    },

    surveyEmbed: (node: RichNode, index: number) => {
      const surveyId = str(node.attrs?.surveyId)
      if (!surveyId) return null
      return (
        <Link
          key={index}
          to={`/learn/surveys?s=${surveyId}`}
          className="my-3 flex items-center gap-2.5 rounded-lg border border-amber/40 bg-amber/5 px-3 py-2.5 text-sm text-text transition-colors hover:border-amber"
        >
          <ClipboardList className="h-5 w-5 shrink-0 text-amber" />
          <span className="min-w-0 flex-1">Пройдите опрос — это часть урока</span>
          <ExternalLink className="h-4 w-4 shrink-0 text-text3" />
        </Link>
      )
    },

    checkQuestion: (node: RichNode, index: number) => {
      const blockId = str(node.attrs?.blockId)
      const question = str(node.attrs?.question)
      const options = Array.isArray(node.attrs?.options)
        ? (node.attrs.options as unknown[]).map((o) => String(o))
        : []
      if (!blockId || !question || options.length < 2) return null
      return (
        <CheckQuestion
          key={`${blockId}-${index}`}
          lessonId={lesson.id}
          blockId={blockId}
          question={question}
          options={options}
          gateNext={Boolean(node.attrs?.gateNext)}
          initialAnswer={answers[blockId]}
          lessonCompleted={lesson.completed}
          onAnswered={onBlockAnswered}
        />
      )
    },
  }

  return (
    <>
      <RichRenderer value={lesson.content} extraNodes={extraNodes} className={className} />
      {lightbox && (
        <ImageLightbox
          images={lightbox.images}
          index={lightbox.index}
          onIndexChange={(i) => setLightbox({ ...lightbox, index: i })}
          open
          onOpenChange={(open) => {
            if (!open) setLightbox(null)
          }}
        />
      )}
    </>
  )
}
