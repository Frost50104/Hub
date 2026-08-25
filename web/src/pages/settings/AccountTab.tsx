import { Award, BookOpen, ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useLearnProfile, useMyCertificates } from '@/hooks/useLearn'
import { useMe } from '@/hooks/useMe'
import { guideRows } from '@/lib/guides'
import { ORG_ROLE_LABEL } from '@/lib/learn'

function tenureLabel(days: number): string {
  if (days < 30) return `${days} дн.`
  if (days < 365) return `${Math.floor(days / 30)} мес.`
  const years = Math.floor(days / 365)
  const months = Math.floor((days % 365) / 30)
  return months ? `${years} г. ${months} мес.` : `${years} г.`
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

/**
 * «Учётная запись» — данные сотрудника: «Работа» (должность, точка, отдел,
 * контур, стаж — из учебного профиля), «Инструкция» и «Сертификаты». Профиля
 * может не быть вовсе (сотрудник только трекера): тогда блок «Работа» не
 * рисуется, а 404 от `/learn/profile` — не ошибка экрана.
 */
export function AccountTab() {
  const me = useMe()
  const learn = useLearnProfile()
  const certificates = useMyCertificates()
  // Ссылки подписаны сервером и приходят вместе с /me: получать их по клику
  // нельзя — `window.open` после await блокируют попап-фильтры.
  const guides = guideRows(me.data)

  const work: [string, string | null][] = learn.data?.profile_id
    ? [
        ['Должность', learn.data.position_name],
        ['Основная точка', learn.data.store_name],
        ['Отдел', learn.data.department_name],
        ['Контур', learn.data.org_role ? ORG_ROLE_LABEL[learn.data.org_role] : null],
        ['Организация', me.data?.tenant_slug ? me.data.tenant_slug.toUpperCase() : null],
        [
          'В команде с',
          learn.data.hired_at
            ? fmtDate(learn.data.hired_at)
            : learn.data.tenure_days !== null
              ? tenureLabel(learn.data.tenure_days)
              : null,
        ],
      ]
    : [['Организация', me.data?.tenant_slug ? me.data.tenant_slug.toUpperCase() : null]]
  const workRows = work.filter((r): r is [string, string] => Boolean(r[1]))

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-[11px]">
        <h2 className="font-display text-[17px] font-bold leading-[1.25] text-text">Работа</h2>
        {learn.isLoading ? (
          <div className="h-24 rounded-[14px] bg-surface" aria-hidden />
        ) : workRows.length > 0 ? (
          // По макету «Настройки»: dl с рядами 11×14px и радиусом 10, а не
          // мобильный блок свойств (48px, правый отступ под контролы — текстовые
          // значения прилипали к рамке).
          <dl className="m-0 overflow-hidden rounded-[10px] border border-glass-border">
            {workRows.map(([label, value]) => (
              <div
                key={label}
                className="flex items-center justify-between gap-4 border-t border-hair px-3.5 py-[11px] first:border-t-0"
              >
                <dt className="text-[15px] text-text2">{label}</dt>
                <dd className="m-0 min-w-0 text-right text-[15px] font-semibold text-text">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-[14px] text-text2">Данных о должности и точке пока нет.</p>
        )}
      </section>

      {guides.length > 0 && (
        <section className="flex flex-col gap-[11px]">
          <h2 className="font-display text-[17px] font-bold leading-[1.25] text-text">
            Инструкция
          </h2>
          {/* Тот же списковый вид, что «Сертификаты»: третьего вида блока на
              этом экране быть не должно (макет «Настройки»). */}
          <ul className="flex flex-col overflow-hidden rounded-[10px] border border-glass-border">
            {guides.map((guide) => (
              <li key={guide.kind} className="border-t border-hair first:border-t-0">
                <a
                  href={guide.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex min-h-12 items-center gap-3 px-3.5 py-2 hover:bg-glass focus-visible:bg-glass focus-visible:outline-none"
                >
                  <BookOpen className="h-[18px] w-[18px] shrink-0 text-text2" strokeWidth={1.8} />
                  {/* Подпись целиком в одной надписи: вторая, мелкая справа,
                      была единственным отличием двух строк у админа. */}
                  <span className="min-w-0 flex-1 truncate text-[15px] font-semibold text-text">
                    {guide.label}
                  </span>
                  <ExternalLink
                    className="h-4 w-4 shrink-0 text-text2"
                    strokeWidth={1.8}
                    aria-hidden
                  />
                </a>
              </li>
            ))}
          </ul>
          <p className="text-[13px] leading-[1.45] text-text2">
            Откроется в новой вкладке. Ссылка личная — она работает несколько часов.
          </p>
        </section>
      )}

      <section className="flex flex-col gap-[11px]">
        <h2 className="font-display text-[17px] font-bold leading-[1.25] text-text">Сертификаты</h2>
        {(certificates.data?.length ?? 0) > 0 ? (
          <ul className="flex flex-col overflow-hidden rounded-[10px] border border-glass-border">
            {certificates.data!.map((cert) => (
              <li key={cert.id} className="border-t border-hair first:border-t-0">
                <Link
                  to={`/learn/certificates/${cert.id}`}
                  className="flex min-h-12 items-center gap-3 px-3.5 py-2 hover:bg-glass focus-visible:outline-none focus-visible:bg-glass"
                >
                  <Award className="h-[18px] w-[18px] shrink-0 text-text2" strokeWidth={1.8} />
                  <span className="min-w-0 flex-1 truncate text-[15px] font-semibold text-text">
                    {cert.course_title}
                  </span>
                  <span className="shrink-0 text-[13px] text-text2">{fmtDate(cert.issued_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-[10px] border border-dashed border-glass-border p-4 text-[15px] leading-[1.5] text-text2">
            Пока нет сертификатов. Они появляются после пройденных курсов с аттестацией.
          </p>
        )}
      </section>
    </div>
  )
}
