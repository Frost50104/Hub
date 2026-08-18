import {
  Archive,
  BadgeCheck,
  BookOpen,
  ChevronRight,
  CircleAlert,
  ClipboardList,
  Clock,
  GraduationCap,
  Newspaper,
  ShoppingBag,
  Sparkles,
  Trophy,
} from 'lucide-react'
import { SpaceSwitcher } from '@/components/layout/SpaceSwitcher'
import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { CourseCover, courseTypeBadgeClass } from '@/components/learn/CourseCover'
import { Skeleton } from '@/components/ui/Skeleton'
import { useLearnHome, useRecent } from '@/hooks/useLearn'
import { useMe } from '@/hooks/useMe'
import { cn } from '@/lib/cn'
import {
  CONTENT_TYPE_LABEL,
  COURSE_TYPE_LABEL,
  type HomeCourse,
  type HomeData,
} from '@/lib/learn'
import { nbsp, plural } from '@/lib/typography'

/**
 * Витрина «Обучение» (Ф4, ТЗ §3). Порядок задаёт срочность, а не структура
 * базы: шесть блоков разного веса вместо шести одинаковых списков.
 *
 * Инвариант блоков: одна сущность не встречается дважды на одном экране —
 * «Моё обучение» вычитает всё, что уже поднято в «Сейчас важно».
 */

const MAX_URGENT = 3
const MAX_IN_PROGRESS = 3

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

function isOverdue(iso: string | null): boolean {
  return Boolean(iso && new Date(iso) < new Date())
}

function Section({
  title,
  tone = 'neutral',
  action,
  children,
}: {
  title: string
  tone?: 'neutral' | 'urgent'
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-2.5">
      <p className="flex items-center justify-between gap-2">
        <span
          className={cn(
            'flex items-center gap-2 text-xs font-bold uppercase tracking-[0.09em]',
            tone === 'urgent' ? 'text-red' : 'text-text2',
          )}
        >
          {tone === 'urgent' && <CircleAlert className="h-[15px] w-[15px]" strokeWidth={2.2} />}
          {title}
        </span>
        {action}
      </p>
      {children}
    </section>
  )
}

/** Строка-ссылка одной геометрии: плитка 40px + заголовок + мета. */
function Row({
  to,
  icon,
  title,
  meta,
  trailing,
  accent,
}: {
  to: string
  icon: ReactNode
  title: string
  meta: string
  trailing?: ReactNode
  accent?: boolean
}) {
  return (
    <Link
      to={to}
      className={cn(
        'flex min-h-[56px] items-center gap-3 rounded-[14px] border px-3.5 py-3',
        accent ? 'border-amber/40 bg-amber/[0.06]' : 'border-hair bg-tint',
      )}
    >
      <span
        className={cn(
          'flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px]',
          accent ? 'bg-amber text-on-amber' : 'bg-surface text-text2',
        )}
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[16px] font-semibold leading-[1.35] text-text">
          {title}
        </span>
        <span className="mt-0.5 block text-[13px] text-text2">{nbsp(meta)}</span>
      </span>
      {trailing ?? <ChevronRight className="h-[18px] w-[18px] shrink-0 text-text2" />}
    </Link>
  )
}

/** Карточка курса, требующего действия сейчас: со своим CTA внутри. */
function UrgentCourseCard({ course }: { course: HomeCourse }) {
  const overdue = isOverdue(course.due_at)
  const pct =
    course.lessons_total > 0
      ? Math.round((course.lessons_completed / course.lessons_total) * 100)
      : 0
  return (
    <Link
      to={`/learn/courses/${course.id}`}
      className={cn(
        'flex flex-col gap-2.5 rounded-[14px] border p-3.5',
        overdue ? 'border-red/45 bg-red/[0.06]' : 'border-amber/40 bg-amber/[0.06]',
      )}
    >
      <span className="flex items-center gap-2">
        <span
          className={cn(
            'h-[22px] px-2 text-[11px]',
            overdue
              ? 'inline-flex items-center rounded-md bg-red font-bold uppercase tracking-[0.08em] text-bg'
              : courseTypeBadgeClass(course.course_type),
          )}
        >
          {overdue ? 'Просрочено' : COURSE_TYPE_LABEL[course.course_type]}
        </span>
        {course.due_at && (
          <span className="text-[13px] text-text">
            {nbsp(
              overdue
                ? `дедлайн был ${shortDate(course.due_at)}`
                : `до ${shortDate(course.due_at)}`,
            )}
          </span>
        )}
      </span>
      <span className="block text-[18px] font-semibold leading-[1.35] text-text">
        {course.title}
      </span>
      <span className="flex items-center gap-2.5">
        <span className="block h-1 flex-1 overflow-hidden rounded-full bg-surface">
          <span
            className={cn('block h-full rounded-full', overdue ? 'bg-red' : 'bg-amber')}
            style={{ width: `${pct}%` }}
          />
        </span>
        <span className="text-xs tabular-nums text-text2">
          {nbsp(`${course.lessons_completed} из ${course.lessons_total}`)}
        </span>
      </span>
      <span className="inline-flex h-11 items-center justify-center gap-2 rounded-[10px] bg-amber text-[15px] font-semibold text-on-amber">
        Продолжить сейчас
      </span>
    </Link>
  )
}

function NoveltyIcon({ type }: { type: string }) {
  if (type === 'product') return <ShoppingBag className="h-5 w-5" />
  if (type === 'news') return <Newspaper className="h-5 w-5" />
  if (type === 'course') return <GraduationCap className="h-5 w-5" />
  return <Sparkles className="h-5 w-5" />
}

export function LearnHomePage() {
  const me = useMe()
  const home = useLearnHome()
  const recent = useRecent()
  const isAdmin = me.data?.hub_role === 'admin'
  const [showAllUrgent, setShowAllUrgent] = useState(false)

  const archived = me.data?.profile?.status === 'archived'
  const needsRestore = me.data?.profile_needs_restore
  const data: HomeData | undefined = home.data

  const today = new Date().toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    weekday: 'long',
  })

  // Блок 1 — всё, что требует действия по сроку.
  const urgentCourses = useMemo(
    () => (data?.courses ?? []).filter((c) => c.due_at !== null),
    [data],
  )
  const urgentItems = useMemo(
    () => [
      ...urgentCourses.map((c) => ({ kind: 'course' as const, course: c })),
      ...(data?.pending_acks ?? []).map((a) => ({ kind: 'ack' as const, ack: a })),
    ],
    [urgentCourses, data],
  )
  const visibleUrgent = showAllUrgent ? urgentItems : urgentItems.slice(0, MAX_URGENT)

  // Блок 2 вычитает поднятое в блок 1: один курс не может встретиться дважды.
  const urgentIds = useMemo(() => new Set(urgentCourses.map((c) => c.id)), [urgentCourses])
  const inProgress = useMemo(
    () =>
      (data?.courses ?? [])
        .filter(
          (c) =>
            !urgentIds.has(c.id) &&
            c.lessons_completed > 0 &&
            c.lessons_completed < c.lessons_total,
        )
        .slice(0, MAX_IN_PROGRESS),
    [data, urgentIds],
  )

  const isEmpty =
    data !== undefined &&
    !archived &&
    !needsRestore &&
    urgentItems.length === 0 &&
    inProgress.length === 0 &&
    data.assessments.length === 0 &&
    data.surveys.length === 0 &&
    data.novelties.length === 0 &&
    (recent.data?.length ?? 0) === 0

  return (
    // На десктопе шире 680: правый рельс не должен зажимать основную колонку.
    <div className="mx-auto max-w-[680px] lg:max-w-[1000px] lg:px-4">
      <header className="px-5 pt-11">
        {/* Симметрично HomePage: на мобильном это единственный видимый способ
            вернуться в «Задачи» — десктопный сайдбар тут не рендерится. */}
        <SpaceSwitcher className="mb-4 lg:hidden" />
        <p className="mb-1 text-xs leading-[1.35] text-text2 first-letter:uppercase">
          {today}
        </p>
        <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
          Обучение
        </h1>
      </header>

      {(archived || needsRestore) && (
        <div className="mx-5 mt-5 flex items-start gap-3 rounded-[14px] border border-hair bg-tint p-4">
          <Archive className="mt-0.5 h-5 w-5 shrink-0 text-amber" />
          <div>
            <p className="text-[15px] font-semibold text-text">
              {archived ? 'Ваша карточка сотрудника в архиве' : 'Карточка ожидает восстановления'}
            </p>
            <p className="mt-0.5 text-[13px] text-text2">
              Материалы обучения недоступны. Обратитесь к администратору или в отдел
              персонала.
            </p>
          </div>
        </div>
      )}

      {home.isLoading && (
        <div className="space-y-3 px-5 pt-6">
          <Skeleton className="h-3 w-28" />
          <Skeleton className="h-[132px] w-full" />
          <Skeleton className="h-[84px] w-full" />
          <Skeleton className="h-[84px] w-full" />
        </div>
      )}

      {isEmpty && (
        <div className="flex flex-col items-center gap-3.5 px-7 py-[72px] text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-amber text-on-amber">
            <GraduationCap className="h-[26px] w-[26px]" strokeWidth={1.7} />
          </span>
          <h2 className="font-display text-xl font-bold leading-[1.25] text-text lg:text-[22px]">
            Добро пожаловать на борт
          </h2>
          <p className="text-[16px] leading-[1.6] text-text2 [text-wrap:pretty]">
            Пока вам ничего не назначено. Курсы появятся здесь, когда наставник откроет
            программу — обычно в первый рабочий день.
          </p>
          <Link
            to="/learn/courses"
            className="inline-flex h-12 items-center justify-center rounded-xl bg-amber px-[22px] text-[15px] font-semibold text-on-amber"
          >
            Посмотреть каталог
          </Link>
        </div>
      )}

      {data && !isEmpty && (
        // Десктоп: срочное и обучение — в основной колонке, «взять, когда
        // будет минута» (рейтинг, аттестации, опросы) — в правом рельсе.
        <div className="px-5 pb-8 pt-5 lg:flex lg:items-start lg:gap-8">
          <div className="flex flex-col gap-7 lg:min-w-0 lg:flex-1">
          {urgentItems.length > 0 && (
            <Section title="Сейчас важно" tone="urgent">
              <div className="flex flex-col gap-2.5">
                {visibleUrgent.map((item) =>
                  item.kind === 'course' ? (
                    <UrgentCourseCard key={item.course.id} course={item.course} />
                  ) : (
                    <Row
                      key={item.ack.id}
                      to={`/learn/library?m=${item.ack.id}`}
                      accent
                      icon={<BookOpen className="h-[19px] w-[19px]" />}
                      title={item.ack.title}
                      meta={
                        item.ack.deadline_at
                          ? `Требует ознакомления до ${shortDate(item.ack.deadline_at)}`
                          : 'Требует ознакомления'
                      }
                    />
                  ),
                )}
                {/* Блок обязан читаться за один взгляд — остальное под кнопкой. */}
                {!showAllUrgent && urgentItems.length > MAX_URGENT && (
                  <button
                    type="button"
                    onClick={() => setShowAllUrgent(true)}
                    className="inline-flex h-11 items-center justify-center rounded-xl border border-hair text-sm font-semibold text-text2 hover:text-text"
                  >
                    Показать ещё {urgentItems.length - MAX_URGENT}
                  </button>
                )}
              </div>
            </Section>
          )}

          {inProgress.length > 0 && (
            <Section
              title="Моё обучение"
              action={
                <Link
                  to="/learn/courses"
                  className="-my-2.5 inline-flex min-h-[44px] items-center text-sm font-semibold text-text2 hover:text-text"
                >
                  Все {data.courses.length} →
                </Link>
              }
            >
              <div className="flex flex-col gap-2">
                {inProgress.map((c, i) => {
                  const pct =
                    c.lessons_total > 0
                      ? Math.round((c.lessons_completed / c.lessons_total) * 100)
                      : 0
                  return (
                    <Link
                      key={c.id}
                      to={`/learn/courses/${c.id}`}
                      className="flex items-center gap-3 rounded-[14px] border border-hair p-2.5"
                    >
                      <CourseCover
                        courseType={c.course_type}
                        index={i}
                        className="h-12 w-12 lg:h-12 lg:w-12"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block text-[16px] font-semibold leading-[1.35] text-text">
                          {c.title}
                        </span>
                        <span className="mt-0.5 block text-[13px] text-text2">
                          {nbsp(`${c.lessons_completed} из ${c.lessons_total} уроков`)}
                        </span>
                        <span className="mt-2 flex items-center gap-2">
                          <span className="block h-1 flex-1 overflow-hidden rounded-full bg-surface">
                            <span
                              className="block h-full rounded-full bg-amber"
                              style={{ width: `${pct}%` }}
                            />
                          </span>
                          <span className="text-[11px] tabular-nums text-text2">{pct}%</span>
                        </span>
                      </span>
                    </Link>
                  )
                })}
              </div>
            </Section>
          )}

          {(recent.data?.length ?? 0) > 0 && (
            <Section title="Недавнее">
              <div className="flex flex-col gap-2">
                {recent.data!.slice(0, 3).map((item) => (
                  <Row
                    key={item.object_type + item.object_id}
                    to={item.url_path}
                    icon={<Clock className="h-[19px] w-[19px]" />}
                    title={item.title}
                    meta={CONTENT_TYPE_LABEL[item.object_type] ?? 'Открывали недавно'}
                    trailing={
                      <span className="shrink-0 text-[13px] font-semibold text-text2">
                        Открыть
                      </span>
                    }
                  />
                ))}
              </div>
            </Section>
          )}

            {data.novelties.length > 0 && (
              <Section title="Новинки">
                <div className="-mx-5 flex snap-x snap-mandatory gap-2.5 overflow-x-auto px-5 pb-1 lg:mx-0 lg:grid lg:grid-cols-2 lg:overflow-visible lg:px-0">
                  {data.novelties.map((n) => (
                    <Link
                      key={`${n.object_type}-${n.object_id}`}
                      to={n.url_path}
                      className="flex w-[200px] shrink-0 snap-start flex-col gap-2 lg:w-auto"
                    >
                      {n.image_url ? (
                        <img
                          src={n.image_url}
                          alt=""
                          loading="lazy"
                          className="block h-28 w-full rounded-xl object-cover"
                        />
                      ) : (
                        <span className="flex h-28 w-full items-center justify-center rounded-xl bg-surface text-text2">
                          <NoveltyIcon type={n.object_type} />
                        </span>
                      )}
                      <span className="block text-[15px] font-semibold leading-[1.35] text-text">
                        {n.title}
                      </span>
                      <span className="block text-[13px] text-text2">
                        {CONTENT_TYPE_LABEL[n.object_type] ?? 'Новинка'}
                      </span>
                    </Link>
                  ))}
                </div>
              </Section>
            )}
          </div>

          <div className="mt-7 flex flex-col gap-7 lg:mt-0 lg:w-[280px] lg:shrink-0">
          {data.rating && (
            <Section title="Рейтинг">
              <Link
                to="/learn/rating"
                className="flex flex-col gap-3.5 rounded-[14px] border border-hair bg-tint p-3.5"
              >
                <span className="flex items-center gap-3.5">
                  <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-amber text-on-amber">
                    <Trophy className="h-[23px] w-[23px]" strokeWidth={1.9} />
                  </span>
                  <span className="flex min-w-0 flex-1 gap-6">
                    <span className="whitespace-nowrap">
                      <span className="block font-display text-[22px] font-bold leading-none tabular-nums text-text">
                        {nbsp(
                          Number.isInteger(data.rating.points)
                            ? String(data.rating.points)
                            : data.rating.points.toFixed(1),
                        )}
                      </span>
                      <span className="mt-1.5 block text-xs text-text2">баллов</span>
                    </span>
                    {data.rating.rank !== null && (
                      <span className="whitespace-nowrap">
                        <span className="block font-display text-[22px] font-bold leading-none tabular-nums text-text">
                          {data.rating.rank}
                          <span className="text-sm text-text2">
                            {nbsp(` / ${data.rating.total_participants}`)}
                          </span>
                        </span>
                        <span className="mt-1.5 block text-xs text-text2">место в сети</span>
                      </span>
                    )}
                  </span>
                </span>
                {/* Нейтральный чип, а не зелёный: зелёная заливка в learn
                    означает «пройдено», а не «выросло». */}
                {data.rating.delta_week > 0 && (
                  <span className="inline-flex items-center gap-1 self-start rounded-md bg-surface px-2 py-1 text-xs font-bold text-text">
                    ↑ {nbsp(`${Math.round(data.rating.delta_week)} за неделю`)}
                  </span>
                )}
              </Link>
            </Section>
          )}
          {(data.assessments.length > 0 || data.surveys.length > 0) && (
            <Section title="Аттестации и опросы">
              <div className="flex flex-col gap-2">
                {data.assessments.map((a) => (
                  <Row
                    key={a.id}
                    to="/learn/assessments"
                    icon={<BadgeCheck className="h-[19px] w-[19px]" />}
                    title={a.title}
                    meta={[
                      a.ends_at ? `Открыта до ${shortDate(a.ends_at)}` : 'Открыта',
                      a.question_count > 0 &&
                        plural(a.question_count, 'вопрос', 'вопроса', 'вопросов'),
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  />
                ))}
                {data.surveys.map((s) => (
                  <Row
                    key={s.id}
                    to={`/learn/surveys?s=${s.id}`}
                    icon={<ClipboardList className="h-[19px] w-[19px]" />}
                    title={s.title}
                    meta={[
                      s.question_count > 0 &&
                        plural(s.question_count, 'вопрос', 'вопроса', 'вопросов'),
                      s.is_anonymous && 'анонимно',
                      s.closes_at && `до ${shortDate(s.closes_at)}`,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  />
                ))}
              </div>
            </Section>
          )}



          {isAdmin && (
            <Section title="Управление">
              <div className="flex flex-col gap-2">
                <Row
                  to="/learn/admin/org"
                  icon={<GraduationCap className="h-[19px] w-[19px]" />}
                  title="Оргструктура"
                  meta="Должности, магазины, франчайзи, отделы, группы"
                />
                <Row
                  to="/learn/admin/employees"
                  icon={<BadgeCheck className="h-[19px] w-[19px]" />}
                  title="Сотрудники"
                  meta="Карточки, архив, импорт из CSV"
                />
                <Row
                  to="/learn/admin/audit"
                  icon={<ClipboardList className="h-[19px] w-[19px]" />}
                  title="Журнал действий"
                  meta="Кто и что менял в системе"
                />
              </div>
            </Section>
          )}
          </div>
        </div>
      )}
    </div>
  )
}
