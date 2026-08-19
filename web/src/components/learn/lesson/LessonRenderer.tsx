import { ChevronRight, ClipboardList, ExternalLink, FileText, Maximize2 } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  RichRenderer,
  type ExtraNodeRenderers,
  type RichNode,
} from '@/components/learn/rich/RichRenderer'
import { type LessonContent } from '@/lib/learn'
import { plural } from '@/lib/typography'

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
    // Иллюстрация выходит за колонку во всю ширину экрана — но через
    // отрицательный margin по паддингу контейнера, а не 100vw: vw включает
    // ширину скроллбара и уводит страницу вбок.
    figure: (node: RichNode, index: number) => {
      const src = str(node.attrs?.src)
      const caption = str(node.attrs?.caption)
      if (!src) return null
      return (
        <figure key={index} className="-mx-5 my-7 lg:mx-0 lg:my-8">
          <button
            type="button"
            onClick={() => setLightbox({ images: [{ src, caption }], index: 0 })}
            className="block w-full cursor-zoom-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:rounded-xl"
            aria-label="Открыть изображение на весь экран"
          >
            <img
              src={src}
              alt={caption || 'Иллюстрация'}
              loading="lazy"
              className="block max-h-[280px] w-full object-cover lg:h-[340px] lg:max-h-none lg:rounded-xl"
            />
          </button>
          <figcaption className="mx-5 mt-2 flex gap-2 text-[13px] leading-[1.45] text-text2 lg:mx-0 lg:text-sm lg:leading-[1.5]">
            <Maximize2 className="mt-[3px] h-3.5 w-3.5 shrink-0" />
            <span>
              {caption ? `${caption}. ` : ''}Нажмите, чтобы увеличить.
            </span>
          </figcaption>
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
        <div
          key={index}
          className="-mx-5 my-7 flex snap-x snap-mandatory gap-3 overflow-x-auto px-5 pb-1.5 lg:mx-0 lg:my-8 lg:grid lg:grid-cols-3 lg:gap-4 lg:overflow-visible lg:px-0"
        >
          {visible.map((item, i) => (
            <figure key={i} className="w-[248px] shrink-0 snap-start lg:w-auto">
              <button
                type="button"
                onClick={() => setLightbox({ images: lightboxImages, index: i })}
                className="relative block w-full cursor-zoom-in rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                aria-label={`Открыть изображение ${i + 1} на весь экран`}
              >
                <img
                  src={item.src}
                  alt={item.caption || `Шаг ${i + 1}`}
                  loading="lazy"
                  className="h-[186px] w-full rounded-xl object-cover lg:h-[150px]"
                />
                <span className="absolute left-2.5 top-2.5 inline-flex items-center rounded-lg bg-[rgb(8_8_14/0.78)] px-2.5 py-1 font-display text-[11px] font-bold tracking-[0.06em] text-[#F0F0F5]">
                  ШАГ {i + 1} / {visible.length}
                </span>
              </button>
              {item.caption && (
                <figcaption className="mt-2 text-sm leading-[1.45] text-text2">
                  {item.caption}
                </figcaption>
              )}
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
        <div key={index} className="my-7 space-y-2 lg:my-8">
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
      const count = Number(node.attrs?.questionCount)
      // Шеврон, а не внешняя стрелка: опрос уводит внутрь продукта.
      return (
        <Link
          key={index}
          to={`/learn/surveys?s=${surveyId}`}
          className="my-7 flex min-h-[44px] items-center gap-3 rounded-xl border border-amber/35 bg-amber/[0.07] px-4 py-3.5 transition-colors hover:border-amber lg:my-8"
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] bg-amber text-on-amber lg:h-11 lg:w-11">
            <ClipboardList className="h-[19px] w-[19px]" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[16px] font-semibold text-text lg:text-[17px]">
              Опрос
            </span>
            <span className="mt-0.5 block text-sm text-text2 lg:text-[15px]">
              {Number.isFinite(count) && count > 0
                ? `${plural(count, 'вопрос', 'вопроса', 'вопросов')} · часть урока`
                : 'часть урока'}
            </span>
          </span>
          <ChevronRight className="h-[18px] w-[18px] shrink-0 text-text2" />
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
