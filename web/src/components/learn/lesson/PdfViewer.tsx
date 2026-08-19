import { ExternalLink, FileText, FileWarning } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
// ?worker&url — worker через Vite-pipeline бандлится в .js-чанк (es-format,
// см. vite.config worker.format): голый ?url оставил бы .mjs-asset, который
// nginx 1.24 отдал бы application/octet-stream, а module-worker'ы жёстко
// требуют JS-MIME — падало бы ТОЛЬКО на проде (dev-сервер MIME ставит сам).
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?worker&url'

import { Skeleton } from '@/components/ui/Skeleton'
import { cn } from '@/lib/cn'
import { nbsp } from '@/lib/typography'

// workerSrc, не workerPort: каждый документ получает СВОЙ worker — несколько
// pdfEmbed-блоков в одном уроке не делят один порт (одноместная грабля pdf.js).
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const MAX_PAGES = 100
const MAX_DPR = 2
// Потолок площади канваса на страницу (~16.7 Mpx — лимит iOS Safari).
const MAX_CANVAS_PIXELS = 16 * 1024 * 1024

// pdf.js v6 требует Promise.withResolvers (Chrome 119+ / Safari 17.4+);
// старым браузерам отдаём fallback-карточку, не роняя lazy-чанк.
// (типизация через cast — tsconfig lib ES2022 метода ещё не знает)
const SUPPORTED =
  typeof (Promise as { withResolvers?: unknown }).withResolvers === 'function'

type ViewerState = 'loading' | 'ready' | 'error'

/**
 * Клиентский PDF-вьювер (pdf.js, canvas-рендер страниц). Заменяет <iframe>:
 * Android Chrome не рендерит PDF во встраиваниях («контент заблокирован»),
 * iOS показывал только первую страницу. Текстового слоя (выделение) в v1 нет.
 *
 * Default export — обязателен для React.lazy; pdfjs-dist импортируется
 * ТОЛЬКО из этого модуля (иначе Rollup выделит vendor-чанк мимо globIgnores).
 */
export default function PdfViewer({
  src,
  data,
  title,
  fallbackHref,
  className,
}: {
  /** Подписанный URL медиа (уроки). Взаимоисключимо с `data`. */
  src?: string
  /**
   * Готовые байты документа (библиотека: файл качается с Bearer'ом).
   *
   * Blob-URL сюда передавать НЕЛЬЗЯ: для не-http(s) источника pdf.js берёт
   * XHR-поток, а `connect-src` в CSP не содержит `blob:` — запрос падает со
   * статусом 0, и вьювер показывает «не удалось отобразить». Проверено на
   * staging 2026-08-19.
   */
  data?: Uint8Array
  title?: string
  /** Ссылка «Открыть в новой вкладке» в error-карточке (нет при forbidDownload). */
  fallbackHref?: string
  className?: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<ViewerState>('loading')
  const [pageCount, setPageCount] = useState(0)
  const [shownPages, setShownPages] = useState(0)
  const [renderWidth, setRenderWidth] = useState(0)

  // Ширина контейнера: initial + ResizeObserver (гейт 8px — от циклов
  // и дрожания скроллбара; поворот телефона перерисовывает страницы).
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    setRenderWidth(el.clientWidth)
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0
      setRenderWidth((prev) => (Math.abs(prev - w) > 8 ? w : prev))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const container = containerRef.current
    if (!SUPPORTED || !container || renderWidth <= 0) return

    if (!src && !data) return

    let cancelled = false
    // Один GET вместо range-чанков: media-локация под limit_req 60 r/s,
    // а размер вложений ограничен 20MB — стриминг не нужен.
    // Байты копируем на каждый заход: pdf.js передаёт буфер воркеру
    // (transfer), и повторный рендер — например после смены ширины —
    // получил бы уже отсоединённый.
    const task = pdfjs.getDocument(
      data
        ? { data: new Uint8Array(data) }
        : { url: src, disableRange: true, disableAutoFetch: true },
    )

    void (async () => {
      const doc = await task.promise
      if (cancelled) return
      setPageCount(doc.numPages)
      const total = Math.min(doc.numPages, MAX_PAGES)
      container.replaceChildren()

      // Последовательный рендер: пик памяти низкий, event loop дышит.
      for (let pageNo = 1; pageNo <= total; pageNo++) {
        if (cancelled) return
        const page = await doc.getPage(pageNo)
        const base = page.getViewport({ scale: 1 })
        const cssScale = renderWidth / base.width
        let ratio = Math.min(window.devicePixelRatio || 1, MAX_DPR)
        const area = base.width * base.height * cssScale * cssScale
        if (area * ratio * ratio > MAX_CANVAS_PIXELS) {
          ratio = Math.sqrt(MAX_CANVAS_PIXELS / area)
        }
        const viewport = page.getViewport({ scale: cssScale * ratio })

        const canvas = document.createElement('canvas')
        canvas.width = Math.floor(viewport.width)
        canvas.height = Math.floor(viewport.height)
        canvas.className = 'block w-full rounded-md border border-hair bg-white'
        const ctx = canvas.getContext('2d')
        if (!ctx) throw new Error('canvas 2d context unavailable')
        container.append(canvas)

        await page.render({ canvas, canvasContext: ctx, viewport }).promise
        if (cancelled) return
        if (pageNo === 1) setState('ready')
        setShownPages(pageNo)
      }
    })().catch(() => {
      // Битый файл / 403 истёкшей подписи / HTML вместо PDF — одна карточка.
      if (!cancelled) setState('error')
    })

    return () => {
      cancelled = true
      void task.destroy() // терминирует и worker документа
    }
  }, [src, data, renderWidth])

  if (!SUPPORTED || state === 'error') {
    return (
      <div
        className={cn(
          'flex flex-col items-center gap-2 rounded-lg border border-glass-border bg-glass p-6 text-center',
          className,
        )}
      >
        <FileWarning className="h-8 w-8 text-text3" />
        <p className="text-sm text-text2">
          Не удалось отобразить PDF{state === 'error' ? ' — обновите страницу' : ' в этом браузере'}.
        </p>
        {fallbackHref && (
          <a
            href={fallbackHref}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-amber hover:opacity-80"
          >
            Открыть в новой вкладке <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </div>
    )
  }

  return (
    <div
      className={cn(
        'overflow-hidden rounded-[14px] border border-glass-border bg-tint',
        className,
      )}
    >
      {/* Тулбар в две строки на мобильном: в одну имя файла сжималось до
          «Карта на…», а три кнопки по 44px в 360px не помещаются. */}
      <div className="flex flex-col gap-1 border-b border-hair bg-surface px-2.5 py-2 lg:flex-row lg:items-center lg:gap-3 lg:px-3.5">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber/[0.14] text-amber lg:h-[34px] lg:w-[34px]">
            <FileText className="h-4 w-4" />
          </span>
          <p className="min-w-0 flex-1 truncate text-[13px] font-semibold text-text lg:text-sm">
            {title || 'Документ PDF'}
          </p>
        </div>
        <div className="flex items-center justify-between gap-2 lg:justify-end">
          {state === 'ready' && pageCount > 0 && (
            <span className="text-[13px] tabular-nums text-text2 lg:text-sm">
              {pageCount > MAX_PAGES
                ? nbsp(`Первые ${MAX_PAGES} из ${pageCount} стр.`)
                : nbsp(`${shownPages} из ${pageCount} стр.`)}
            </span>
          )}
          {fallbackHref && (
            <a
              href={fallbackHref}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Открыть в новой вкладке"
              title="Открыть в новой вкладке"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text"
            >
              <ExternalLink className="h-[18px] w-[18px]" />
            </a>
          )}
        </div>
      </div>

      <div className="p-2">
        {state === 'loading' && <Skeleton className="h-[70vh] w-full rounded-md" />}
        {/* Контейнер НЕ прячем display:none — скрытый div имеет clientWidth 0
            и рендер никогда бы не стартовал; пустой блок высоты не добавляет. */}
        <div
          ref={containerRef}
          role="document"
          aria-label={title || 'Документ PDF'}
          className="space-y-2"
        />
      </div>
    </div>
  )
}
