import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Award, ImagePlus, Printer, Trash2 } from 'lucide-react'
import { useRef, useState, type ChangeEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useMe } from '@/hooks/useMe'
import { learnApi, type CertificateInfo } from '@/lib/learn'

/**
 * Сертификат о прохождении курса (Ф3b, v1 = страница + браузерная печать).
 * @media print в globals.css прячет навигацию — печатается только рамка.
 *
 * ОС 19.08 «сертификат должен быть в фирменном стиле»: hub-admin загружает
 * подложку прямо здесь — результат видно сразу, отдельного экрана настроек в
 * learn-домене нет. Подложка — <img>, а НЕ background-image: фоновые картинки
 * браузеры по умолчанию не печатают, и на бумаге остался бы голый текст.
 */
export function CertificatePage() {
  const { certificateId } = useParams<{ certificateId: string }>()
  const me = useMe()
  const isAdmin = me.data?.hub_role === 'admin'
  const fileInput = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)

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

  return (
    <div className="mx-auto max-w-3xl">
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex flex-wrap items-center justify-between gap-2 print-hide">
          <Link
            to="/learn/rating"
            className="inline-flex items-center gap-1.5 text-sm text-text3 hover:text-text"
          >
            <ArrowLeft className="h-4 w-4" /> К рейтингу
          </Link>
          <div className="flex flex-wrap gap-2">
            {isAdmin && (
              <>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => fileInput.current?.click()}
                >
                  <ImagePlus className="h-4 w-4" />
                  {cert.data?.background_url ? 'Сменить подложку' : 'Своя подложка'}
                </Button>
                {cert.data?.background_url && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    onClick={() => void applyBackground(null)}
                  >
                    <Trash2 className="h-4 w-4" /> Убрать
                  </Button>
                )}
              </>
            )}
            {cert.data && (
              <Button size="sm" variant="secondary" onClick={() => window.print()}>
                <Printer className="h-4 w-4" /> Распечатать
              </Button>
            )}
          </div>
        </div>

        {isAdmin && (
          <>
            <input
              ref={fileInput}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              hidden
              onChange={(e) => void onPick(e)}
            />
            <p className="text-[13px] leading-[1.45] text-text2 print-hide">
              Подложка общая для всей сети. Лучше всего лист A4 в альбомной
              ориентации (например 2480×1754) со свободной серединой — поверх неё
              печатаются имя, курс и дата.
            </p>
          </>
        )}

        {cert.isLoading && <SkeletonRows rows={5} />}
        {cert.isError && <QueryError onRetry={() => void cert.refetch()} />}

        {cert.data && <CertificateSheet cert={cert.data} />}
      </div>
    </div>
  )
}

function CertificateSheet({ cert }: { cert: CertificateInfo }) {
  const issued = new Date(cert.issued_at).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })

  if (cert.background_url) {
    return (
      <div
        id="certificate-print"
        className="relative overflow-hidden rounded-2xl"
        // Размеры текста — в cqw (доля ШИРИНЫ подложки), а не в vw: страница
        // сертификата ограничена max-w-3xl, и на широком мониторе vw дал бы
        // подпись крупнее самой картинки.
        style={{ containerType: 'inline-size' }}
      >
        <img
          src={cert.background_url}
          alt=""
          className="block h-auto w-full"
          // Печать: подложка — обычная картинка, поэтому уходит на бумагу
          // без «печатать фоновые изображения» в диалоге печати.
        />
        {/* Текст поверх подложки — в процентах от её высоты, чтобы макет
            не разъезжался на другом соотношении сторон. */}
        <div className="absolute inset-0 flex flex-col items-center justify-center px-[12%] text-center">
          <p
            className="font-display font-bold leading-[1.15] text-[#08080E] drop-shadow-[0_1px_0_rgba(255,255,255,0.65)]"
            style={{ fontSize: 'clamp(15px, 4.4cqw, 44px)' }}
          >
            {cert.full_name}
          </p>
          <p
            className="mt-[1.2%] leading-[1.3] text-[#08080E]/85"
            style={{ fontSize: 'clamp(9px, 2cqw, 19px)' }}
          >
            успешно {'прошёл(-ла)'} курс
          </p>
          <p
            className="mt-[0.6%] font-display font-semibold leading-[1.25] text-[#08080E]"
            style={{ fontSize: 'clamp(11px, 2.6cqw, 26px)' }}
          >
            «{cert.course_title}»
          </p>
          <p
            className="mt-[2%] tabular-nums text-[#08080E]/75"
            style={{ fontSize: 'clamp(8px, 1.6cqw, 15px)' }}
          >
            № {cert.serial} · {issued}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div
      id="certificate-print"
      className="rounded-2xl border-4 border-double border-amber/60 bg-glass px-6 py-10 text-center lg:px-12 lg:py-14"
    >
      <Award className="mx-auto h-12 w-12 text-amber" />
      <p className="mt-4 text-xs font-semibold uppercase tracking-[0.3em] text-text3">
        Сертификат
      </p>
      <p className="mt-3 text-sm text-text2">подтверждает, что</p>
      <p className="mt-2 font-display text-3xl font-bold text-text">{cert.full_name}</p>
      <p className="mt-3 text-sm text-text2">успешно {'прошёл(-ла)'} курс</p>
      <p className="mt-2 font-display text-xl font-semibold text-amber">
        «{cert.course_title}»
      </p>
      <div className="mx-auto mt-8 flex max-w-md items-center justify-between border-t border-glass-border pt-4 text-xs text-text3">
        <span>№ {cert.serial}</span>
        <span>{issued}</span>
        <span>Signaris Hub</span>
      </div>
    </div>
  )
}
