import { Award, BookOpen, ExternalLink, MessageSquarePlus, UserPen } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { FeedbackDialog } from '@/components/settings/FeedbackDialog'
import { InfoRow, InfoRows } from '@/components/ui/InfoRows'
import { useLearnProfile, useMyCertificates } from '@/hooks/useLearn'
import { useMe } from '@/hooks/useMe'
import { AUTH_PROFILE_URL } from '@/lib/auth'
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
 * Один силуэт строки на ВСЕ списки экрана: «Профиль и связь», «Инструкция»,
 * «Сертификаты». Кнопки «по содержимому» рядом со строками во всю ширину
 * читались как чужой элемент — на узком экране особенно.
 */
const ROW_CLASS =
  'flex min-h-12 w-full items-center gap-3 px-3.5 py-2 text-left hover:bg-glass focus-visible:bg-glass focus-visible:outline-none'

function RowList({ children }: { children: ReactNode }) {
  return (
    <ul className="flex flex-col overflow-hidden rounded-[10px] border border-glass-border">
      {children}
    </ul>
  )
}

function RowItem({ children }: { children: ReactNode }) {
  return <li className="border-t border-hair first:border-t-0">{children}</li>
}

/** Подпись строки: 15/600, обрезается многоточием, а не ломает строку. */
function RowLabel({ children }: { children: ReactNode }) {
  return (
    <span className="min-w-0 flex-1 truncate text-[15px] font-semibold text-text">
      {children}
    </span>
  )
}

/**
 * «Учётная запись» — данные сотрудника: «Работа» (должность, точка, отдел,
 * контур, стаж — из учебного профиля), «Профиль и связь», «Инструкция» и
 * «Сертификаты». Профиля может не быть вовсе (сотрудник только трекера):
 * тогда блок «Работа» не рисуется, а 404 от `/learn/profile` — не ошибка
 * экрана.
 */
export function AccountTab() {
  const [feedbackOpen, setFeedbackOpen] = useState(false)
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
          <InfoRows>
            {workRows.map(([label, value]) => (
              <InfoRow key={label} label={label}>
                {value}
              </InfoRow>
            ))}
          </InfoRows>
        ) : (
          <p className="text-[14px] text-text2">Данных о должности и точке пока нет.</p>
        )}
      </section>

      <section className="flex flex-col gap-[11px]">
        <h2 className="font-display text-[17px] font-bold leading-[1.25] text-text">
          Профиль и связь
        </h2>
        <RowList>
          <RowItem>
            {/* Имя, аватар, пароль и 2FA живут в auth — один профиль на все
                продукты Signaris, и редактировать их надо там. Обычная ссылка,
                а не программный переход: человек должен видеть, куда идёт. */}
            <a
              href={AUTH_PROFILE_URL}
              target="_blank"
              rel="noopener noreferrer"
              className={ROW_CLASS}
            >
              <UserPen className="h-[18px] w-[18px] shrink-0 text-text2" strokeWidth={1.8} />
              <RowLabel>Редактировать профиль</RowLabel>
              <ExternalLink
                className="h-4 w-4 shrink-0 text-text2"
                strokeWidth={1.8}
                aria-hidden
              />
            </a>
          </RowItem>
          <RowItem>
            <button type="button" onClick={() => setFeedbackOpen(true)} className={ROW_CLASS}>
              <MessageSquarePlus
                className="h-[18px] w-[18px] shrink-0 text-text2"
                strokeWidth={1.8}
              />
              <RowLabel>Обратная связь</RowLabel>
            </button>
          </RowItem>
        </RowList>
        <p className="text-[13px] leading-[1.45] text-text2">
          Профиль откроется в новой вкладке — имя, фото и пароль общие для всех
          продуктов Signaris.
        </p>
      </section>

      {guides.length > 0 && (
        <section className="flex flex-col gap-[11px]">
          <h2 className="font-display text-[17px] font-bold leading-[1.25] text-text">
            Инструкция
          </h2>
          {/* Тот же списковый вид, что «Сертификаты»: третьего вида блока на
              этом экране быть не должно (макет «Настройки»). */}
          <RowList>
            {guides.map((guide) => (
              <RowItem key={guide.kind}>
                <a
                  href={guide.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={ROW_CLASS}
                >
                  <BookOpen className="h-[18px] w-[18px] shrink-0 text-text2" strokeWidth={1.8} />
                  {/* Подпись целиком в одной надписи: вторая, мелкая справа,
                      была единственным отличием двух строк у админа. */}
                  <RowLabel>{guide.label}</RowLabel>
                  <ExternalLink
                    className="h-4 w-4 shrink-0 text-text2"
                    strokeWidth={1.8}
                    aria-hidden
                  />
                </a>
              </RowItem>
            ))}
          </RowList>
          <p className="text-[13px] leading-[1.45] text-text2">
            Откроется в новой вкладке. Ссылка личная — она работает несколько часов.
          </p>
        </section>
      )}

      <section className="flex flex-col gap-[11px]">
        <h2 className="font-display text-[17px] font-bold leading-[1.25] text-text">Сертификаты</h2>
        {(certificates.data?.length ?? 0) > 0 ? (
          <RowList>
            {certificates.data!.map((cert) => (
              <RowItem key={cert.id}>
                <Link to={`/learn/certificates/${cert.id}`} className={ROW_CLASS}>
                  <Award className="h-[18px] w-[18px] shrink-0 text-text2" strokeWidth={1.8} />
                  <RowLabel>{cert.course_title}</RowLabel>
                  <span className="shrink-0 text-[13px] text-text2">{fmtDate(cert.issued_at)}</span>
                </Link>
              </RowItem>
            ))}
          </RowList>
        ) : (
          <p className="rounded-[10px] border border-dashed border-glass-border p-4 text-[15px] leading-[1.5] text-text2">
            Пока нет сертификатов. Они появляются после пройденных курсов с аттестацией.
          </p>
        )}
      </section>

      <FeedbackDialog open={feedbackOpen} onOpenChange={setFeedbackOpen} />
    </div>
  )
}
