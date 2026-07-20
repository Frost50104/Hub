import { useState } from 'react'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useAuditLog } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { type AuditEntry } from '@/lib/learn'

const ACTION_LABEL: Record<string, string> = {
  create: 'создал',
  update: 'изменил',
  delete: 'удалил',
  publish: 'опубликовал',
  archive: 'архивировал',
  restore: 'восстановил',
  access_change: 'изменил доступы',
  import: 'импортировал',
}

const OBJECT_LABEL: Record<string, string> = {
  employee_profile: 'Сотрудник',
  position: 'Должность',
  store: 'Магазин',
  franchisee: 'Франчайзи',
  department: 'Отдел',
  position_group: 'Группа должностей',
  store_group: 'Группа магазинов',
  franchisee_group: 'Группа франчайзи',
  user_group: 'Группа сотрудников',
  audience: 'Аудитория',
  library_section: 'Раздел библиотеки',
  library_material: 'Материал',
  news_post: 'Новость',
  survey: 'Опрос',
  course: 'Курс',
  course_lesson: 'Урок',
  lesson_template: 'Шаблон урока',
  quiz: 'Тест',
  quiz_attempt: 'Попытка теста',
  certificate: 'Сертификат',
  product_category: 'Категория товаров',
  product: 'Товар',
  automation_rule: 'Автосценарий',
  shift_posting: 'Смена',
  shift_application: 'Отклик на смену',
  assessment_campaign: 'Аттестация',
  automation_job: 'Задание автосценария',
  learning_settings: 'Настройки обучения',
}

const OBJECT_FILTERS = Object.entries(OBJECT_LABEL)

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function DiffLine({ entry }: { entry: AuditEntry }) {
  if (!entry.diff) return null
  const parts = Object.entries(entry.diff).map(
    ([field, change]) =>
      `${field}: ${String(change.old ?? '—')} → ${String(change.new ?? '—')}`,
  )
  if (parts.length === 0) return null
  return <p className="mt-0.5 truncate text-[11px] text-text3">{parts.join('; ')}</p>
}

export function LearnAuditPage() {
  const isDesktop = useIsDesktop()
  const [objectType, setObjectType] = useState('')
  const [offset, setOffset] = useState(0)

  const audit = useAuditLog({
    object_type: objectType || undefined,
    offset,
  })

  return (
    <div className="mx-auto max-w-4xl">
      {!isDesktop && <MobilePageHeader eyebrow="Управление" title="Журнал" />}
      <div className="space-y-4 p-4 lg:p-8">
        {isDesktop && (
          <h1 className="font-display text-2xl font-bold text-text">Журнал действий</h1>
        )}
        <Select
          className="w-56"
          value={objectType}
          onChange={(e) => {
            setObjectType(e.target.value)
            setOffset(0)
          }}
        >
          <option value="">Все объекты</option>
          {OBJECT_FILTERS.map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </Select>

        {audit.isLoading && <SkeletonRows rows={8} />}
        {audit.isError && <QueryError onRetry={() => void audit.refetch()} />}
        {audit.data && (
          <>
            <ul className="divide-y divide-glass-border rounded-xl border border-glass-border bg-glass">
              {audit.data.items.length === 0 && (
                <li className="p-4 text-sm text-text3">Записей пока нет.</li>
              )}
              {audit.data.items.map((e) => (
                <li key={e.id} className="px-4 py-2.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="min-w-0 truncate text-sm text-text">
                      <span className="font-medium">{e.actor_name ?? 'Система'}</span>{' '}
                      <span className="text-text2">
                        {ACTION_LABEL[e.action] ?? e.action}
                      </span>{' '}
                      <span className="text-text3">
                        {(OBJECT_LABEL[e.object_type] ?? e.object_type).toLowerCase()}
                      </span>{' '}
                      {e.object_label && <span className="font-medium">«{e.object_label}»</span>}
                    </p>
                    <span className="shrink-0 text-[11px] text-text3">
                      {formatWhen(e.created_at)}
                    </span>
                  </div>
                  <DiffLine entry={e} />
                </li>
              ))}
            </ul>
            {offset + 50 < audit.data.total && (
              <Button
                variant="secondary"
                className="w-full"
                onClick={() => setOffset((o) => o + 50)}
              >
                Следующие 50 (осталось {audit.data.total - offset - 50})
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
