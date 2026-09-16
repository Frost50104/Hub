import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Circle, CircleDashed } from 'lucide-react'

import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { cn } from '@/lib/cn'
import { type EmployeeProgressCourse, learnApi } from '@/lib/learn'
import { accountNote, mandatoryShort, orgLine } from '@/lib/learnProgress'
import { shortDate } from '@/lib/taskDates'

/**
 * Разбор обучения по одному человеку: какие курсы пройдены, какие нет.
 *
 * Цвета расставлены скупо и по спеке Claude Design: зелёная — только галочка
 * завершённого курса, красный — только у просрочки. Если красить каждую
 * непройденную строку, панель на десять курсов превращается в радугу, а
 * «пройденное приглушается, а не подсвечивается».
 *
 * Числа в шапке берутся из ОТВЕТА, а не пересчитываются из списка курсов:
 * аудитории материализованы и пересчитываются фоном, так что два независимых
 * счёта могут лечь по разные стороны пересчёта — и админ увидит «4 из 6»
 * рядом с семью обязательными строками.
 */
export function EmployeeProgressDialog({
  profileId,
  onClose,
}: {
  profileId: string
  onClose: () => void
}) {
  const detail = useQuery({
    queryKey: ['learn-progress-employee', profileId],
    queryFn: () => learnApi.employeeProgressDetail(profileId),
    staleTime: 60_000,
    meta: { suppressGlobalError: true },
  })

  const d = detail.data
  const required = d?.courses.filter((c) => c.required) ?? []
  const rest = d?.courses.filter((c) => !c.required) ?? []
  const note = d ? accountNote(d.profile) : null

  return (
    <ResponsiveDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      title={d?.profile.full_name ?? 'Прогресс сотрудника'}
      description="Курсы, сертификаты и последние тесты — считает сервер"
      desktopWidth={640}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Закрыть
        </Button>
      }
    >
      {detail.isLoading && <SkeletonRows rows={5} />}
      {detail.isError && <QueryError onRetry={() => void detail.refetch()} />}

      {d && (
        <div className="flex flex-col gap-4">
          <div>
            <p className="text-[13px] text-text2">{orgLine(d.profile)}</p>
            <p className="mt-1 font-display text-[17px] font-bold tabular-nums text-text">
              {d.profile.mandatory_total > 0
                ? `Обязательные: ${mandatoryShort(d.profile.mandatory_done, d.profile.mandatory_total)}`
                : 'Обязательных курсов не назначено'}
            </p>
          </div>

          {note && (
            // Нейтральная плашка: отсутствие учётки — не ошибка человека.
            <p className="rounded-xl border border-hair bg-tint p-3 text-[14px] text-text">
              {note === 'нет учётки — в Hub не заходил'
                ? 'Учётки в Hub нет — человек не заходил ни разу. Прогресс появится после первого входа.'
                : 'Человек ещё не заходил в Hub — прогресс появится после первого входа.'}
            </p>
          )}

          <CourseSection title="Обязательные" courses={required} />
          <CourseSection title="Остальные курсы" courses={rest} />

          <section className="flex flex-col gap-2">
            <h3 className="text-[12px] font-bold uppercase tracking-[0.09em] text-text2">
              Последние тесты
            </h3>
            {d.attempts.length === 0 ? (
              <p className="text-[14px] text-text2">Попыток пока не было.</p>
            ) : (
              <ul className="flex flex-col">
                {d.attempts.map((a, i) => (
                  <li
                    key={a.attempt_id}
                    className={cn(
                      'flex items-center justify-between gap-2.5 py-[9px] text-[14px]',
                      i > 0 && 'border-t border-hair',
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate text-text">{a.quiz_title}</span>
                    <span className="shrink-0 tabular-nums text-text2">
                      {a.score_pct !== null ? `${a.score_pct}%` : '—'}
                      {a.finished_at ? ` · ${shortDate(a.finished_at)}` : ''}
                    </span>
                    <span
                      className={cn(
                        'inline-flex h-[22px] shrink-0 items-center rounded-md px-2 text-[12px] font-semibold',
                        a.state === 'passed'
                          ? 'bg-green-deep text-bg'
                          : a.state === 'failed'
                            ? 'bg-red text-bg'
                            : 'bg-surface text-text2',
                      )}
                    >
                      {ATTEMPT_LABEL[a.state]}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </ResponsiveDialog>
  )
}

const ATTEMPT_LABEL: Record<string, string> = {
  passed: 'сдан',
  failed: 'не сдан',
  pending_review: 'на проверке',
  in_progress: 'не завершён',
}

function CourseSection({
  title,
  courses,
}: {
  title: string
  courses: EmployeeProgressCourse[]
}) {
  if (courses.length === 0) return null
  return (
    <section className="flex flex-col gap-1">
      <h3 className="text-[12px] font-bold uppercase tracking-[0.09em] text-text2">
        {title}
      </h3>
      <div className="flex flex-col">
        {courses.map((c, i) => (
          <CourseRow key={c.course_id} course={c} first={i === 0} />
        ))}
      </div>
    </section>
  )
}

function CourseRow({ course, first }: { course: EmployeeProgressCourse; first: boolean }) {
  const done = course.status === 'completed'
  const overdue =
    !done && course.due_at !== null && new Date(course.due_at).getTime() < Date.now()
  const Icon = done ? CheckCircle2 : course.status === 'in_progress' ? CircleDashed : Circle

  return (
    <div className={cn('flex items-start gap-2.5 py-[9px]', !first && 'border-t border-hair')}>
      <Icon
        className={cn('mt-[3px] h-4 w-4 shrink-0', done ? 'text-green-deep' : 'text-text3')}
      />
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium leading-[1.4] text-text">
          {course.title}
          {course.course_status !== 'published' && (
            <span className="ml-1.5 text-[13px] text-text3">· снят с публикации</span>
          )}
        </span>
        <span className={cn('mt-0.5 block text-[13px]', overdue ? 'text-red' : 'text-text2')}>
          {courseStateText(course)}
          {overdue && course.due_at && ` · просрочен с ${shortDate(course.due_at)}`}
          {course.certificate_serial && ` · сертификат ${course.certificate_serial}`}
        </span>
      </span>
    </div>
  )
}

function courseStateText(course: EmployeeProgressCourse): string {
  if (course.status === 'completed') {
    return course.completed_at ? `завершён ${shortDate(course.completed_at)}` : 'завершён'
  }
  if (course.status === 'in_progress') {
    return `${Math.min(course.lessons_completed, course.lessons_total)} из ${course.lessons_total} уроков`
  }
  return 'не начат'
}
