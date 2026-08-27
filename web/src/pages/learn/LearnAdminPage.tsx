import { useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ADMIN_SEGMENTS, adminSegmentsFor, type AdminSegment } from '@/components/layout/learnNav'
import { EmptyState } from '@/components/ui/EmptyState'
import { SegmentGroup, type SegmentOption } from '@/components/ui/SegmentGroup'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'

import { AdminEmbedContext } from './adminEmbed'
import { LearnAnalyticsPage } from './LearnAnalyticsPage'
import { LearnAuditPage } from './LearnAuditPage'
import { LearnAutomationsPage } from './LearnAutomationsPage'
import { LearnEmployeesPage } from './LearnEmployeesPage'
import { LearnOrgPage } from './LearnOrgPage'
import { LearnReviewPage } from './LearnReviewPage'

/**
 * «Управление» — один маршрут `/learn/admin?tab=…` с шестью сегментами
 * (макет «Урок — редизайн», route admin; решение владельца 20.08:
 * Оргструктура — шестым сегментом). Гейты — ПО СЕГМЕНТАМ, как проверяет
 * бэкенд: Проверка и Аналитика открыты publisher'ам, ТУ/франчайзи/офису и
 * hub-admin; Сотрудники, Автосценарии, Журнал, Оргструктура — hub-admin.
 * Недоступный `?tab=` по deep-link → первый доступный. Шесть прежних
 * страниц рендерятся вкладками без своих шапок (контекст `AdminEmbedContext`);
 * старые URL `/learn/admin/<seg>` — редиректы навсегда (push и старые
 * уведомления хранят их).
 */

const SUBTITLE: Record<AdminSegment, string> = {
  review: 'Очередь попыток с открытыми вопросами — закрытые оценены автоматически.',
  analytics: 'Прохождение курсов, провалы тестов и ознакомления — срез считает сервер.',
  employees: 'Учётные карточки сотрудников, роли контента и привязка входов.',
  automations: 'Правила «новичок → курс с дедлайном» и правило неактивности.',
  audit: 'Кто, что и когда менял — только метаполя, без содержимого ответов.',
  org: 'Должности, магазины, франчайзи, отделы, группы и доступ.',
}

const TAB_COMPONENT: Record<AdminSegment, () => JSX.Element> = {
  review: LearnReviewPage,
  analytics: LearnAnalyticsPage,
  employees: LearnEmployeesPage,
  automations: LearnAutomationsPage,
  audit: LearnAuditPage,
  org: LearnOrgPage,
}

export function LearnAdminPage() {
  const isDesktop = useIsDesktop()
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const allowed = useMemo(() => adminSegmentsFor(me.data), [me.data])

  const requested = params.get('tab') as AdminSegment | null
  const active: AdminSegment | null =
    requested && allowed.includes(requested) ? requested : (allowed[0] ?? null)

  // Недоступная или пустая вкладка в URL — переписываем на первую доступную,
  // чтобы ссылка из адресной строки оставалась честной.
  useEffect(() => {
    if (active && requested !== active) {
      const next = new URLSearchParams(params)
      next.set('tab', active)
      setParams(next, { replace: true })
    }
  }, [active, requested, params, setParams])

  const options: SegmentOption<AdminSegment>[] = ADMIN_SEGMENTS.filter((s) => allowed.includes(s.key)).map(
    (s) => ({ value: s.key, label: s.label }),
  )
  const meta = ADMIN_SEGMENTS.find((s) => s.key === active) ?? null
  const Tab = active ? TAB_COMPONENT[active] : null

  return (
    <div className="mx-auto max-w-[880px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
      <header className="flex flex-col gap-4">
        <div className="min-w-0">
          <p className="mb-1 text-[12px] leading-[1.35] text-text2 lg:hidden">Управление</p>
          <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
            {meta?.title ?? 'Управление'}
          </h1>
          {meta && <p className="mt-2.5 hidden text-[15px] text-text2 lg:block">{SUBTITLE[meta.key]}</p>}
        </div>
        {options.length > 0 && (
          <div className="-mx-5 overflow-x-auto px-5 pb-1 [scrollbar-width:none] lg:mx-0 lg:px-0">
            <SegmentGroup
              ariaLabel="Раздел управления"
              options={options}
              value={active ?? options[0]!.value}
              onChange={(v) => {
                const next = new URLSearchParams(params)
                next.set('tab', v)
                setParams(next)
              }}
              size={isDesktop ? 'md' : 'lg'}
              className="w-max"
            />
          </div>
        )}
      </header>

      <div className="mt-5">
        {me.isLoading && <SkeletonRows rows={5} />}
        {me.data && allowed.length === 0 && (
          <EmptyState
            layout="card"
            title="Здесь пока нечего управлять"
            text="Разделы управления открываются публикаторам, руководителям магазинов и администраторам. Если вы ждёте доступ — напишите администратору Hub."
          />
        )}
        {Tab && (
          <AdminEmbedContext.Provider value>
            <Tab key={active} />
          </AdminEmbedContext.Provider>
        )}
      </div>
    </div>
  )
}
