import { ClipboardList, ExternalLink, FileText } from 'lucide-react'
import { Link } from 'react-router-dom'

import {
  RichRenderer,
  type ExtraNodeRenderers,
  type RichNode,
} from '@/components/learn/rich/RichRenderer'
import { type LessonContent } from '@/lib/learn'

import { CheckQuestion } from './CheckQuestion'
import { VideoPlayer } from './VideoPlayer'

/**
 * Рендер контента урока (Ф3a) = RichRenderer + доменные ноды. БЕЗ ProseMirror.
 * media-ноды приходят с сервера уже с подписанным attrs.src; correct у
 * checkQuestion вырезан (проверка ответа — только на сервере).
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

  const extraNodes: ExtraNodeRenderers = {
    figure: (node: RichNode, index: number) => {
      const src = str(node.attrs?.src)
      const caption = str(node.attrs?.caption)
      if (!src) return null
      return (
        <figure key={index} className="my-3">
          <img
            src={src}
            alt={caption || 'Иллюстрация'}
            loading="lazy"
            className="max-h-[480px] w-auto max-w-full rounded-lg border border-glass-border"
          />
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
      return (
        <div key={index} className="my-3 flex gap-2 overflow-x-auto pb-1">
          {visible.map((item, i) => (
            <figure key={i} className="w-44 shrink-0 sm:w-56">
              <img
                src={item.src}
                alt={item.caption || `Шаг ${i + 1}`}
                loading="lazy"
                className="h-32 w-full rounded-lg border border-glass-border object-cover sm:h-40"
              />
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
      // Подписанный URL работает без Bearer — обычная ссылка открывается.
      return (
        <a
          key={index}
          href={src}
          target="_blank"
          rel="noopener noreferrer"
          className="my-3 flex items-center gap-2.5 rounded-lg border border-glass-border bg-surface px-3 py-2.5 text-sm text-text transition-colors hover:border-amber/50"
        >
          <FileText className="h-5 w-5 shrink-0 text-amber" />
          <span className="min-w-0 flex-1 truncate">Открыть документ PDF</span>
          <ExternalLink className="h-4 w-4 shrink-0 text-text3" />
        </a>
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

  return <RichRenderer value={lesson.content} extraNodes={extraNodes} className={className} />
}
