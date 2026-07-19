import { Award, Bell, ChevronRight, Globe, LogOut, Palette, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { Avatar } from '@/components/ui/Avatar'
import { useLearnProfile, useMyCertificates } from '@/hooks/useLearn'
import { useMe } from '@/hooks/useMe'
import { authClient } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { ORG_ROLE_LABEL } from '@/lib/learn'

function tenureLabel(days: number): string {
  if (days < 30) return `${days} дн.`
  if (days < 365) return `${Math.floor(days / 30)} мес.`
  const years = Math.floor(days / 365)
  const months = Math.floor((days % 365) / 30)
  return months ? `${years} г. ${months} мес.` : `${years} г.`
}

/** Фото из auth (публичный /api/avatars/{id}); фолбэк — инициалы. */
function ProfileAvatar({
  avatarUrl,
  name,
  email,
}: {
  avatarUrl: string | null
  name?: string
  email?: string
}) {
  const [broken, setBroken] = useState(false)
  if (avatarUrl && !broken) {
    return (
      <img
        src={avatarUrl}
        alt={name || 'Аватар'}
        onError={() => setBroken(true)}
        className="h-24 w-24 rounded-full border border-glass-border object-cover"
      />
    )
  }
  return <Avatar name={name} email={email} className="h-24 w-24 text-xl" />
}

const HUB_ROLE_LABEL: Record<'admin' | 'member' | 'viewer', string> = {
  admin: 'Администратор',
  member: 'Сотрудник',
  viewer: 'Наблюдатель',
}

/**
 * Mobile-only "Профиль" page (the desktop sidebar already has logout and
 * settings shortcuts). Layout mirrors Asana mobile: edit pencil left, title
 * centered, large avatar block, two-button row, sectioned settings rows.
 */
export function ProfilePage() {
  const me = useMe()
  const learn = useLearnProfile()
  const certificates = useMyCertificates()
  return (
    <>
      <MobilePageHeader
        title="Учётная запись"
        trailing={
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md text-text3 hover:bg-glass hover:text-text"
            aria-label="Редактировать"
          >
            <Pencil className="h-5 w-5" />
          </button>
        }
      />

      <div className="space-y-5 px-4">
        {/* Identity block */}
        <section className="flex flex-col items-center gap-2 pt-2">
          <ProfileAvatar
            avatarUrl={learn.data?.avatar_url ?? null}
            name={me.data?.full_name}
            email={me.data?.email}
          />
          <h2 className="font-display text-xl font-semibold text-text">
            {me.data?.full_name || me.data?.email || 'Пользователь'}
          </h2>
          {me.data?.email && (
            <p className="text-sm text-text3">{me.data.email}</p>
          )}
          {learn.data?.status_text && (
            <p className="rounded-full border border-glass-border bg-glass px-3 py-1 text-xs text-text2">
              {learn.data.status_text}
            </p>
          )}
        </section>

        {/* Workspace + product role */}
        <section>
          <SectionHeader>Учётная запись</SectionHeader>
          <ul className="overflow-hidden rounded-2xl border border-glass-border bg-bg-alt/60">
            <li className="flex items-center gap-3 px-4 py-3 active:bg-glass">
              <span
                className={cn(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-md',
                  'bg-amber/20 font-display text-[11px] font-black uppercase text-amber',
                )}
              >
                {(me.data?.tenant_slug?.slice(0, 2) ?? 'HU').toUpperCase()}
              </span>
              <span className="flex-1 text-sm text-text">
                {me.data?.tenant_slug?.toUpperCase() ?? 'Hub'}
              </span>
              {me.data?.hub_role && (
                <span className="rounded bg-glass px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-text3">
                  {HUB_ROLE_LABEL[me.data.hub_role]}
                </span>
              )}
            </li>
          </ul>
        </section>

        {/* Learn: работа и стаж (Ф4) */}
        {learn.data?.profile_id && (
          <section>
            <SectionHeader>Работа</SectionHeader>
            <ul className="overflow-hidden rounded-2xl border border-glass-border bg-bg-alt/60">
              {(
                [
                  ['Должность', learn.data.position_name],
                  ['Магазин', learn.data.store_name],
                  ['Отдел', learn.data.department_name],
                  [
                    'Контур',
                    learn.data.org_role ? ORG_ROLE_LABEL[learn.data.org_role] : null,
                  ],
                  [
                    'Стаж',
                    learn.data.tenure_days !== null
                      ? tenureLabel(learn.data.tenure_days)
                      : null,
                  ],
                ] as const
              )
                .filter(([, value]) => value)
                .map(([label, value], i) => (
                  <li
                    key={label}
                    className={cn(
                      'flex items-center justify-between gap-3 px-4 py-3',
                      i > 0 && 'border-t border-glass-border/60',
                    )}
                  >
                    <span className="text-sm text-text3">{label}</span>
                    <span className="text-sm text-text">{value}</span>
                  </li>
                ))}
            </ul>
          </section>
        )}

        {/* Learn: сертификаты (Ф3b/Ф4) */}
        {(certificates.data?.length ?? 0) > 0 && (
          <section>
            <SectionHeader>Сертификаты</SectionHeader>
            <ul className="overflow-hidden rounded-2xl border border-glass-border bg-bg-alt/60">
              {certificates.data!.map((cert, i) => (
                <li key={cert.id} className={cn(i > 0 && 'border-t border-glass-border/60')}>
                  <Link
                    to={`/learn/certificates/${cert.id}`}
                    className="flex items-center gap-3 px-4 py-3 active:bg-glass"
                  >
                    <Award className="h-5 w-5 shrink-0 text-amber" />
                    <span className="min-w-0 flex-1 truncate text-sm text-text">
                      {cert.course_title}
                    </span>
                    <ChevronRight className="h-4 w-4 shrink-0 text-text3" />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Settings */}
        <section>
          <SectionHeader>Настройки</SectionHeader>
          <ul className="overflow-hidden rounded-2xl border border-glass-border bg-bg-alt/60">
            <li>
              <Link
                to="/settings/notifications"
                className="flex items-center gap-3 px-4 py-3 active:bg-glass"
              >
                <Bell className="h-5 w-5 text-text3" />
                <span className="flex-1 text-sm text-text">Уведомления</span>
                <ChevronRight className="h-4 w-4 text-text3" />
              </Link>
            </li>
            <li className="border-t border-glass-border/60">
              <Link
                to="/settings/appearance"
                className="flex items-center gap-3 px-4 py-3 active:bg-glass"
              >
                <Palette className="h-5 w-5 text-text3" />
                <span className="flex-1 text-sm text-text">Оформление</span>
                <ChevronRight className="h-4 w-4 text-text3" />
              </Link>
            </li>
            <li className="border-t border-glass-border/60">
              <button
                type="button"
                className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-glass"
              >
                <Globe className="h-5 w-5 text-text3" />
                <span className="flex-1 text-sm text-text">
                  Язык <span className="text-text3">(скоро)</span>
                </span>
              </button>
            </li>
          </ul>
        </section>

        {/* Logout */}
        <section>
          <button
            type="button"
            onClick={() => {
              void authClient.logout()
            }}
            className="flex w-full items-center justify-center gap-2 rounded-2xl border border-red/30 bg-bg-alt/60 px-4 py-3 text-sm font-medium text-red active:bg-red/10"
          >
            <LogOut className="h-4 w-4" />
            Выйти
          </button>
        </section>
      </div>
    </>
  )
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="px-2 pb-1 text-[11px] uppercase tracking-wider text-text3">
      {children}
    </h2>
  )
}
