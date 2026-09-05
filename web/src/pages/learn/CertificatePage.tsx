import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Award, Download, ImagePlus, Printer, Trash2, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState, type ChangeEvent, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { QueryError } from '@/components/QueryError'
import { isStandalone } from '@/lib/standalone'
import { Button } from '@/components/ui/Button'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useMe } from '@/hooks/useMe'
import { cn } from '@/lib/cn'
import { learnApi, type CertificateInfo } from '@/lib/learn'
import { nbsp, plural } from '@/lib/typography'

/**
 * Сертификат о прохождении курса (Ф3b) по макету «Урок — редизайн» (route
 * cert). Два режима: загружена фирменная подложка (ОС 19.08) — текст поверх
 * `<img>` (background-image браузеры не печатают); нет — ТИПОГРАФСКИЙ ЛИСТ
 * 1123×794 (A4 landscape при 96 dpi): кремовая бумага и тушь — единственные
 * литеральные цвета в системе, потому что это документ, который печатают и
 * вешают на стену, а у бумаги тёмной темы не бывает. Лист один на все
 * экраны и на печать: на телефоне миниатюра (масштаб от ширины) + данные
 * документа строками + полноэкранный просмотр с прокруткой по одной оси; на
 * десктопе лист во всю колонку и «Скачать PDF» = печать браузером
 * (`@page A4 landscape`). Серверный PDF отложен (см. docs/TECH_DEBT.md).
 */

const SHEET_W = 1123
const SHEET_H = 794

function formatIssued(iso: string): string {
  // NBSP внутри даты: «2 августа 2026 г.» на 356px рвалось так, что «г.»
  // уезжало на вторую строку одиноким слогом.
  return new Date(iso)
    .toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
    .replace(/ /g, ' ')
}

function certMeta(cert: CertificateInfo): string | null {
  const parts: string[] = []
  if (cert.lessons_count) parts.push(plural(cert.lessons_count, 'урок', 'урока', 'уроков'))
  if (cert.best_score_pct !== null && cert.best_score_pct !== undefined) parts.push(`тест ${cert.best_score_pct}%`)
  return parts.length ? nbsp(parts.join(' · ')) : null
}

/** Печать: в iOS-PWA `window.print()` ненадёжен — открываем ту же страницу в браузере. */
function printCertificate() {
  if (isStandalone()) {
    window.open(window.location.href, '_blank', 'noopener')
    toast.message('Сертификат открыт в браузере — сохраните его в PDF оттуда.')
    return
  }
  window.print()
}

// ─── Лист ────────────────────────────────────────────────────────────────────

const PAPER: CSSProperties = {
  width: SHEET_W,
  height: SHEET_H,
  background: '#FBF9F4',
  color: '#14141C',
  // Гильошир: две тонкие сетки под 45° и точечный растр на 5–7% амбера —
  // узор виден на бумаге, но не мешает читать имя.
  backgroundImage:
    'repeating-linear-gradient(45deg, rgba(176,120,0,.055) 0 1px, transparent 1px 9px),' +
    'repeating-linear-gradient(-45deg, rgba(176,120,0,.055) 0 1px, transparent 1px 9px),' +
    'radial-gradient(rgba(176,120,0,.10) .9px, transparent 1.1px)',
  backgroundSize: 'auto, auto, 16px 16px',
}
const MUTED: CSSProperties = { color: 'rgba(20,20,28,.62)' }
const RULE: CSSProperties = { display: 'block', height: 1, background: 'rgba(20,20,28,.22)' }
const GOLD = '#C08A00'

/** Сведённый лист: геометрия печати, масштабируется снаружи через transform. */
function TypographicSheet({ cert, scale, shadow = true, print = false }: { cert: CertificateInfo; scale: number; shadow?: boolean; print?: boolean }) {
  const meta = certMeta(cert)
  return (
    <div
      data-cert-print={print ? '1' : undefined}
      className="absolute left-0 top-0 grid origin-top-left grid-rows-[auto_1fr_auto] gap-3.5 overflow-hidden px-16 pb-[38px] pt-[46px] text-center"
      style={{
        ...PAPER,
        transform: `scale(${scale})`,
        boxShadow: shadow ? '0 14px 40px rgba(0,0,0,.4)' : undefined,
      }}
    >
      <span className="pointer-events-none absolute inset-3.5 border-[1.5px]" style={{ borderColor: GOLD }} />
      <span className="pointer-events-none absolute inset-5 border-[0.5px]" style={{ borderColor: 'rgba(20,20,28,.28)' }} />
      {/* Угловые засечки — четыре L-образных штриха поверх рамки. */}
      <span className="pointer-events-none absolute left-[22px] top-[22px] h-[26px] w-[26px] border-l-2 border-t-2" style={{ borderColor: GOLD }} />
      <span className="pointer-events-none absolute right-[22px] top-[22px] h-[26px] w-[26px] border-r-2 border-t-2" style={{ borderColor: GOLD }} />
      <span className="pointer-events-none absolute bottom-[22px] left-[22px] h-[26px] w-[26px] border-b-2 border-l-2" style={{ borderColor: GOLD }} />
      <span className="pointer-events-none absolute bottom-[22px] right-[22px] h-[26px] w-[26px] border-b-2 border-r-2" style={{ borderColor: GOLD }} />

      <div className="relative flex items-center justify-between gap-5">
        <img src="/brand/signaris-horizontal-on-light.svg" alt="Signaris" className="block h-[26px] w-auto" />
        <div className="text-right">
          <p className="font-display text-[12px] font-bold uppercase tracking-[0.34em]" style={{ color: '#946400' }}>
            Сертификат
          </p>
          <p className="mt-[5px] text-[11px] uppercase tracking-[0.12em]" style={MUTED}>
            Signaris Hub · обучение
          </p>
        </div>
      </div>

      <div className="relative flex flex-col items-center justify-evenly gap-3.5">
        <p className="text-[16px]" style={MUTED}>
          настоящим подтверждается, что
        </p>
        <div className="flex w-full flex-col items-center gap-3">
          <p className="font-display text-[46px] font-bold leading-[1.14] tracking-[-0.015em]">{cert.full_name}</p>
          <span style={{ ...RULE, width: '54%' }} />
          {cert.role_title && (
            <p className="text-[15px]" style={MUTED}>
              {cert.role_title}
            </p>
          )}
        </div>
        <p className="mt-1.5 text-[16px]" style={MUTED}>
          успешно завершил(-а) курс
        </p>
        <p className="max-w-[620px] font-display text-[27px] font-semibold leading-[1.3] [text-wrap:pretty]">
          «{cert.course_title}»
        </p>
        {meta && (
          <p className="mt-1 text-[15px]" style={MUTED}>
            {meta}
          </p>
        )}
      </div>

      <div className="relative grid grid-cols-[1fr_auto_1fr] items-end gap-7">
        <div className="flex flex-col gap-[7px] text-left">
          <span style={RULE} />
          <span className="text-[11px] uppercase tracking-[0.09em]" style={MUTED}>
            Руководитель обучения
          </span>
          <span className="font-mono text-[11px] tracking-[0.14em]" style={MUTED}>
            № {cert.serial}
          </span>
        </div>
        {/* Печать-медальон: единственное плотно-амберное пятно на листе. */}
        <span
          className="flex h-[76px] w-[76px] items-center justify-center rounded-full border-2"
          style={{ borderColor: GOLD, background: '#FFB200', color: '#08080E', boxShadow: '0 0 0 6px rgba(255,178,0,.16)' }}
        >
          <Award className="h-9 w-9" strokeWidth={1.8} />
        </span>
        <div className="flex flex-col gap-[7px] text-right">
          <span className="whitespace-nowrap font-display text-[15px] font-semibold tabular-nums">{formatIssued(cert.issued_at)}</span>
          <span style={RULE} />
          <span className="text-[11px] uppercase tracking-[0.09em]" style={MUTED}>
            Дата выдачи
          </span>
        </div>
      </div>
    </div>
  )
}

/** Лист в коробке: масштаб от ширины коробки, высота коробки = 794·k. */
function SheetBox({ cert, className, print }: { cert: CertificateInfo; className?: string; print?: boolean }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [scale, setScale] = useState(0.3)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setScale(Math.max(0.1, el.clientWidth / SHEET_W))
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return (
    <div ref={ref} className={cn('relative w-full overflow-hidden', className)} style={{ height: SHEET_H * scale }}>
      <TypographicSheet cert={cert} scale={scale} print={print} />
    </div>
  )
}

/** Режим подложки (ОС 19.08): текст поверх `<img>`, размеры в cqw. */
function BackgroundSheet({ cert }: { cert: CertificateInfo }) {
  const issued = formatIssued(cert.issued_at)
  return (
    <div data-cert-print="1" className="relative overflow-hidden rounded-2xl" style={{ containerType: 'inline-size' }}>
      <img src={cert.background_url!} alt="" className="block h-auto w-full" />
      <div className="absolute inset-0 flex flex-col items-center justify-center px-[12%] text-center">
        <p className="font-display font-bold leading-[1.15] text-[#08080E] drop-shadow-[0_1px_0_rgba(255,255,255,0.65)]" style={{ fontSize: 'clamp(15px, 4.4cqw, 44px)' }}>
          {cert.full_name}
        </p>
        <p className="mt-[1.2%] leading-[1.3] text-[#08080E]/85" style={{ fontSize: 'clamp(9px, 2cqw, 19px)' }}>
          успешно завершил(-а) курс
        </p>
        <p className="mt-[0.6%] font-display font-semibold leading-[1.25] text-[#08080E]" style={{ fontSize: 'clamp(11px, 2.6cqw, 26px)' }}>
          «{cert.course_title}»
        </p>
        <p className="mt-[2%] tabular-nums text-[#08080E]/75" style={{ fontSize: 'clamp(8px, 1.6cqw, 15px)' }}>
          № {cert.serial} · {issued}
        </p>
      </div>
    </div>
  )
}

/**
 * Полноэкранный просмотр на телефоне: лист НЕ повёрнут (базовая линия
 * горизонтальна, как у бумаги в руках), масштаб — от высоты области,
 * прокрутка ровно по одной оси — вправо, как у широкой таблицы.
 */
function FullscreenSheet({ cert, onClose }: { cert: CertificateInfo; onClose: () => void }) {
  const areaRef = useRef<HTMLDivElement | null>(null)
  const [scale, setScale] = useState(0.8)
  useLayoutEffect(() => {
    const el = areaRef.current
    if (!el) return
    const update = () => setScale(Math.max(0.2, Math.min(1, (el.clientHeight - 16) / SHEET_H)))
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose])
  return createPortal(
    <div role="dialog" aria-modal="true" aria-label="Сертификат во весь экран" className="fixed inset-0 z-50 flex flex-col" style={{ background: '#0B0B12' }}>
      <div className="flex shrink-0 items-center justify-between gap-2 px-3 pb-1.5 pt-3">
        <button
          type="button"
          onClick={onClose}
          aria-label="Закрыть"
          className="flex h-11 w-11 items-center justify-center rounded-xl text-[#F0F0F5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
          style={{ background: 'rgba(255,255,255,.08)' }}
        >
          <X className="h-5 w-5" strokeWidth={2.2} />
        </button>
        <span className="text-[13px]" style={{ color: '#9090A8' }}>
          Прокрутите вправо — там подписи и печать
        </span>
      </div>
      <div ref={areaRef} className="flex min-h-0 flex-1 items-center overflow-x-auto overflow-y-hidden overscroll-contain">
        <div className="relative shrink-0" style={{ width: SHEET_W * scale, height: SHEET_H * scale }}>
          <TypographicSheet cert={cert} scale={scale} />
        </div>
      </div>
      <div className="flex shrink-0 gap-[9px] px-4 pt-2.5" style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 22px)' }}>
        <Button className="h-12 flex-1 rounded-[14px] text-[16px]" onClick={printCertificate}>
          <Download className="h-[18px] w-[18px]" /> Отправить PDF
        </Button>
      </div>
    </div>,
    document.body,
  )
}

// ─── Страница ────────────────────────────────────────────────────────────────

export function CertificatePage() {
  const { certificateId } = useParams<{ certificateId: string }>()
  const me = useMe()
  const isAdmin = me.data?.hub_role === 'admin'
  const fileInput = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [full, setFull] = useState(false)

  const cert = useQuery({
    queryKey: ['learn-certificate', certificateId],
    queryFn: () => learnApi.certificate(certificateId!),
    enabled: Boolean(certificateId),
  })

  const applyBackground = async (mediaId: string | null) => {
    setBusy(true)
    try {
      await learnApi.setCertificateBackground(mediaId)
      await cert.refetch()
      toast.success(mediaId ? 'Подложка обновлена' : 'Подложка убрана')
    } catch {
      toast.error('Не удалось сохранить подложку')
    } finally {
      setBusy(false)
    }
  }

  const onPick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setBusy(true)
    try {
      const media = await learnApi.uploadMedia(file)
      await learnApi.setCertificateBackground(media.id)
      await cert.refetch()
      toast.success('Подложка обновлена')
    } catch {
      toast.error('Не удалось загрузить подложку')
    } finally {
      setBusy(false)
    }
  }

  const data = cert.data
  const withBackground = Boolean(data?.background_url)
  const meta = data ? certMeta(data) : null

  return (
    <div className="mx-auto max-w-[760px] px-4 pb-16 pt-11 lg:px-8 lg:pt-9">
      <div className="print-hide flex items-center justify-between gap-2">
        <Link
          to="/learn/rating"
          className="-ml-2.5 inline-flex min-h-11 items-center gap-[7px] rounded-lg px-2.5 text-[15px] font-semibold text-text hover:text-amber focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:min-h-10"
        >
          <ArrowLeft className="h-[17px] w-[17px]" strokeWidth={2.2} />
          <span className="hidden lg:inline">Рейтинг</span>
          <span className="sr-only lg:hidden">Назад</span>
        </Link>
        {data && (
          <button
            type="button"
            onClick={printCertificate}
            tabIndex={full ? -1 : 0}
            className="-mr-2.5 inline-flex min-h-11 items-center gap-[7px] rounded-lg px-2.5 text-[15px] font-semibold text-text hover:text-amber focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:hidden"
          >
            <Printer className="h-[17px] w-[17px]" /> Печать
          </button>
        )}
      </div>

      {cert.isLoading && <SkeletonRows rows={5} />}
      {cert.isError && <QueryError onRetry={() => void cert.refetch()} />}

      {data && (
        <>
          {/* Лист: миниатюра на телефоне (тап — во весь экран), на десктопе — во всю колонку. */}
          <div className="mt-2 lg:mt-[18px]">
            {withBackground ? (
              <BackgroundSheet cert={data} />
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setFull(true)}
                  aria-label="Открыть сертификат во весь экран"
                  className="block w-full rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:hidden"
                >
                  <SheetBox cert={data} />
                </button>
                <div className="hidden lg:block">
                  <SheetBox cert={data} print />
                </div>
              </>
            )}
          </div>

          {/* Миниатюра нечитаема по определению, поэтому данные документа
              повторяются строками в шкале прозы. */}
          <dl className="print-hide mt-[18px] flex flex-col gap-[11px] lg:hidden">
            <div className="flex flex-col gap-0.5 border-t border-hair pt-[11px]">
              <dt className="text-[12px] font-bold uppercase tracking-[0.07em] text-text2">Кому выдан</dt>
              <dd className="text-[17px] font-semibold leading-[1.4] text-text">
                {data.full_name}
                {data.role_title && ` · ${data.role_title}`}
              </dd>
            </div>
            <div className="flex flex-col gap-0.5 border-t border-hair pt-[11px]">
              <dt className="text-[12px] font-bold uppercase tracking-[0.07em] text-text2">Курс</dt>
              <dd className="text-[17px] leading-[1.5] text-text">
                «{data.course_title}»{meta && ` · ${meta}`}
              </dd>
            </div>
            <div className="flex flex-col gap-0.5 border-t border-hair pt-[11px]">
              <dt className="text-[12px] font-bold uppercase tracking-[0.07em] text-text2">Номер и дата</dt>
              <dd className="text-[17px] leading-[1.5] text-text">
                <span className="font-mono text-[16px] tracking-[0.06em]">№&nbsp;{data.serial}</span> · {formatIssued(data.issued_at)}
              </dd>
            </div>
          </dl>

          {/* Печать с телефона — самое маловероятное действие в смене, поэтому
              главным стоит отправка файла; на десктопе — «Скачать PDF» + «Печать». */}
          <div className="print-hide mt-[18px] flex flex-col gap-[9px] lg:flex-row lg:flex-wrap">
            <Button className="h-[52px] rounded-[14px] text-[16px] lg:h-11 lg:rounded-xl lg:px-4 lg:text-[15px]" onClick={printCertificate} tabIndex={full ? -1 : 0}>
              <Download className="h-[19px] w-[19px] lg:h-[18px] lg:w-[18px]" />
              <span className="lg:hidden">Отправить PDF</span>
              <span className="hidden lg:inline">Скачать PDF</span>
            </Button>
            <Button variant="secondary" className="hidden h-11 rounded-xl bg-transparent px-4 text-[15px] lg:inline-flex" onClick={printCertificate}>
              <Printer className="h-[18px] w-[18px]" /> Печать
            </Button>
          </div>

          {isAdmin && (
            <div className="print-hide mt-6 flex flex-col gap-2.5 rounded-xl border border-dashed border-glass-border p-3.5">
              <p className="text-[13px] leading-[1.45] text-text2">
                Подложка общая для всей сети. Лучше всего лист A4 в альбомной ориентации (например
                2480×1754) со свободной серединой — поверх неё печатаются имя, курс и дата. Без подложки
                печатается типографский лист.
              </p>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" className="bg-transparent" disabled={busy} onClick={() => fileInput.current?.click()}>
                  <ImagePlus className="h-4 w-4" />
                  {withBackground ? 'Сменить подложку' : 'Своя подложка'}
                </Button>
                {withBackground && (
                  <Button variant="secondary" className="bg-transparent text-red" disabled={busy} onClick={() => void applyBackground(null)}>
                    <Trash2 className="h-4 w-4" /> Убрать подложку
                  </Button>
                )}
              </div>
              <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => void onPick(e)} />
            </div>
          )}
        </>
      )}

      {full && data && !withBackground && <FullscreenSheet cert={data} onClose={() => setFull(false)} />}
    </div>
  )
}
