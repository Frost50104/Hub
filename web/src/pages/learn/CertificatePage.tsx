import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Award, Printer } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { learnApi } from '@/lib/learn'

/**
 * Сертификат о прохождении курса (Ф3b, v1 = страница + браузерная печать).
 * @media print в globals.css прячет навигацию — печатается только рамка.
 */
export function CertificatePage() {
  const { certificateId } = useParams<{ certificateId: string }>()
  const cert = useQuery({
    queryKey: ['learn-certificate', certificateId],
    queryFn: () => learnApi.certificate(certificateId!),
    enabled: Boolean(certificateId),
  })

  return (
    <div className="mx-auto max-w-3xl">
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex items-center justify-between gap-2 print-hide">
          <Link
            to="/learn/rating"
            className="inline-flex items-center gap-1.5 text-sm text-text3 hover:text-text"
          >
            <ArrowLeft className="h-4 w-4" /> К рейтингу
          </Link>
          {cert.data && (
            <Button size="sm" variant="secondary" onClick={() => window.print()}>
              <Printer className="h-4 w-4" /> Распечатать
            </Button>
          )}
        </div>

        {cert.isLoading && <SkeletonRows rows={5} />}
        {cert.isError && <QueryError onRetry={() => void cert.refetch()} />}

        {cert.data && (
          <div
            id="certificate-print"
            className="rounded-2xl border-4 border-double border-amber/60 bg-glass px-6 py-10 text-center lg:px-12 lg:py-14"
          >
            <Award className="mx-auto h-12 w-12 text-amber" />
            <p className="mt-4 text-xs font-semibold uppercase tracking-[0.3em] text-text3">
              Сертификат
            </p>
            <p className="mt-3 text-sm text-text2">подтверждает, что</p>
            <p className="mt-2 font-display text-3xl font-bold text-text">
              {cert.data.full_name}
            </p>
            <p className="mt-3 text-sm text-text2">успешно {'прошёл(-ла)'} курс</p>
            <p className="mt-2 font-display text-xl font-semibold text-amber">
              «{cert.data.course_title}»
            </p>
            <div className="mx-auto mt-8 flex max-w-md items-center justify-between border-t border-glass-border pt-4 text-xs text-text3">
              <span>№ {cert.data.serial}</span>
              <span>
                {new Date(cert.data.issued_at).toLocaleDateString('ru-RU', {
                  day: 'numeric',
                  month: 'long',
                  year: 'numeric',
                })}
              </span>
              <span>Signaris Hub</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
