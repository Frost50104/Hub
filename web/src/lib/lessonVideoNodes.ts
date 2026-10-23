import type { RichDoc, RichNode } from '@/components/learn/rich/RichRenderer'
import type { MediaDetail } from '@/lib/learn'

/**
 * Видео-ноды урока на клиенте (0066): собрать их для гейта публикации и
 * своп «оригинал ↔ чистовик» (инкремент 6). Чистые функции — vitest без jsdom.
 */

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export interface VideoNodeRef {
  mediaId: string
  attrs: Record<string, unknown>
}

function walk(node: RichNode, out: VideoNodeRef[]): void {
  if (node.type === 'video') {
    const mediaId = String(node.attrs?.mediaId ?? '')
    if (UUID_RE.test(mediaId)) out.push({ mediaId: mediaId.toLowerCase(), attrs: node.attrs ?? {} })
  }
  for (const child of node.content ?? []) walk(child, out)
}

/** Все видео-ноды документа в порядке следования (повторы сохраняются). */
export function collectVideoNodes(doc: RichDoc | null | undefined): VideoNodeRef[] {
  const out: VideoNodeRef[] = []
  if (doc?.doc) walk(doc.doc, out)
  return out
}

/** Уникальные mediaId видео документа (нижний регистр). */
export function videoIdsOf(doc: RichDoc | null | undefined): string[] {
  const ids: string[] = []
  for (const ref of collectVideoNodes(doc)) if (!ids.includes(ref.mediaId)) ids.push(ref.mediaId)
  return ids
}

/**
 * Какие видео урока ещё не готовы — по тому, что клиент уже знает из опроса
 * (`['learn-media', id]`). Неизвестное (нет в кэше) считается готовым:
 * последнее слово за сервером (409 на публикацию), а блокировать кнопку по
 * незнанию нельзя.
 */
export function pendingVideoIds(
  doc: RichDoc | null | undefined,
  lookup: (mediaId: string) => Pick<MediaDetail, 'status'> | undefined,
): string[] {
  return videoIdsOf(doc).filter((id) => {
    const status = lookup(id)?.status
    return status === 'processing' || status === 'failed'
  })
}

export interface SwapTarget {
  mediaId: string
  src: string | null
  derivedKind: 'cleaned' | 'composed'
}

/**
 * Атрибуты ноды после замены оригинала производной: `sourceMediaId` ставится
 * ОДИН раз и при второй замене (чистовик → монтаж) не перетирается — иначе
 * «Вернуть оригинал» вернул бы чистовик. Условия досмотра не трогаем.
 */
export function swappedVideoAttrs(
  attrs: Record<string, unknown>,
  target: SwapTarget,
): Record<string, unknown> {
  const current = typeof attrs.mediaId === 'string' ? attrs.mediaId : null
  const source =
    typeof attrs.sourceMediaId === 'string' && attrs.sourceMediaId ? attrs.sourceMediaId : current
  return {
    ...attrs,
    mediaId: target.mediaId,
    src: target.src,
    sourceMediaId: source,
    derivedKind: target.derivedKind,
  }
}

/** Откат к оригиналу: `mediaId` ← `sourceMediaId`, производная забывается. */
export function revertedVideoAttrs(
  attrs: Record<string, unknown>,
  originalSrc: string | null,
): Record<string, unknown> | null {
  const source = typeof attrs.sourceMediaId === 'string' ? attrs.sourceMediaId : null
  if (!source) return null
  return { ...attrs, mediaId: source, src: originalSrc, sourceMediaId: null, derivedKind: null }
}
