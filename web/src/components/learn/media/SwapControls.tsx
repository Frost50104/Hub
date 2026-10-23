import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Confirm } from '@/components/ui/Confirm'
import { learnApi, type MediaDetail } from '@/lib/learn'
import type { SwapTarget } from '@/lib/lessonVideoNodes'
import { swapImpactText } from '@/lib/mediaJobs'

import { useMediaToolsContext } from './MediaToolsContext'

/**
 * «Заменить в уроке» / «Вернуть оригинал» — общие для чистовика и монтажа.
 * Своп — только на клиенте (атрибуты ноды), вступает в силу после
 * сохранения урока; в опубликованном уроке — подтверждение с числом людей
 * из `GET /learn/media/{id}/usage` (макет SwapConfirm). Счётчик ещё не
 * пришёл — кнопка ждёт; ошибка счётчика не блокирует (текст про «никого»).
 */
export function SwapControls({
  base,
  target,
  inUse,
  nodeDerived,
  shorterBy,
  onSwap,
  onRevert,
  children,
}: {
  /** Оригинал — по нему считается, в каких уроках стоит видео. */
  base: MediaDetail
  target: SwapTarget
  /** Нода уже показывает именно эту производную. */
  inUse: boolean
  /** Нода показывает какую-то производную (эту или другую). */
  nodeDerived: boolean
  shorterBy: number | null
  onSwap: (target: SwapTarget) => void
  onRevert: () => void
  /** Дополнительные кнопки в той же строке («Собрать заново»). */
  children?: React.ReactNode
}) {
  const { lessonId, lessonStatus } = useMediaToolsContext()
  const [confirm, setConfirm] = useState(false)
  const usage = useQuery({
    queryKey: ['learn-media', base.id, 'usage'],
    queryFn: () => learnApi.mediaUsage(base.id),
    enabled: confirm && lessonStatus === 'published',
    staleTime: 30_000,
    retry: false,
    meta: { suppressGlobalError: true },
  })
  const inThisLesson = usage.data?.lessons.find((l) => l.lesson_id === lessonId)
  const others = usage.data ? usage.data.lessons.filter((l) => l.lesson_id !== lessonId).length : 0

  const doSwap = () => {
    onSwap(target)
    setConfirm(false)
    toast.success('Видео заменено — сохраните урок', {
      description: 'Оригинал остался, вернуть его можно в любой момент из этой шторки.',
    })
  }
  const swapClick = () => {
    if (lessonStatus === 'published') setConfirm(true)
    else doSwap()
  }
  const label = target.derivedKind === 'composed' ? 'монтаж' : 'чистовик'

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {inUse ? (
          <Button size="sm" variant="secondary" onClick={onRevert}>
            Вернуть оригинал
          </Button>
        ) : (
          <Button size="sm" onClick={swapClick} disabled={nodeDerived && !inUse}>
            Заменить в уроке
          </Button>
        )}
        {children}
      </div>
      {nodeDerived && !inUse && (
        <p className="text-[12px] leading-[1.45] text-text3">
          В уроке уже стоит другая версия этого видео — сначала верните оригинал, потом поставьте{' '}
          {label}.
        </p>
      )}
      <Confirm
        open={confirm}
        onOpenChange={setConfirm}
        title="Заменить видео в опубликованном уроке?"
        text={
          usage.isPending
            ? 'Считаем, сколько человек сейчас проходят урок…'
            : swapImpactText(inThisLesson?.in_progress ?? 0, others, shorterBy)
        }
        confirmLabel="Заменить"
        pending={usage.isPending}
        onConfirm={doSwap}
      />
    </>
  )
}
