import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/cn'

/**
 * Первый вход. Не «заглушка», а экран с одним действием: три группы
 * подсказок показывают, на что ассистент вообще способен — иначе перед
 * пустым полем ввода человек не знает, что спросить.
 *
 * Тона групп несут смысл, а не украшают: амбер — трекер (действия),
 * `--blue-deep` — знание, `--green-deep` — цифры. Красный не занят: он
 * остаётся за просрочкой и ошибками.
 */
const GROUPS = [
  {
    title: 'Задачи',
    tag: 'Трекер',
    tone: 'amber' as const,
    items: [
      'Что просрочено у Дмитрия',
      'Создай задачу на приёмку стенда',
      'Сводка по проекту для планёрки',
      'Кто перегружен на этой неделе',
    ],
  },
  {
    title: 'Обучение',
    tag: 'База знаний',
    tone: 'blue' as const,
    items: [
      'Как приветствовать гостя в час пик',
      'Регламент замены плёнки',
      'Что входит в стандарт подачи',
    ],
  },
]

/** Группа появляется, только когда iiko подключён: предлагать спросить
 *  выручку там, где спрашивать не у кого, — обещание, которое не сдержим. */
const REPORTS_GROUP = {
  title: 'iiko',
  tag: 'Отчёты',
  tone: 'green' as const,
  items: [
    'Выручка по точкам за неделю',
    'Средний чек и динамика',
    'Часы пик по чекам',
    'Списания за прошлый месяц',
  ],
}

export function EmptyState({
  canAct,
  reports,
  onPick,
}: {
  canAct: boolean
  reports: boolean
  onPick: (text: string) => void
}) {
  const groups = reports ? [...GROUPS, REPORTS_GROUP] : GROUPS
  return (
    <div className="mx-auto w-full max-w-3xl">
      <h2 className="font-display text-[22px] font-bold leading-[1.25] text-text lg:text-[26px]">
        Что нужно сделать?
      </h2>
      <p className="mt-2 max-w-[560px] text-[15px] leading-[1.5] text-text2">
        {canAct
          ? 'Напишите обычными словами. Всё, что меняет данные, ассистент сначала покажет планом — и выполнит только после вашего подтверждения.'
          : 'Напишите вопрос обычными словами. Текущий AI-провайдер умеет отвечать по базе знаний, но не выполняет действия.'}
      </p>

      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {groups.map((group) => (
          <div
            key={group.title}
            className="shrink-0 rounded-[14px] border border-glass-border bg-tint p-3.5"
          >
            <div className="flex items-center gap-2.5">
              <p className="font-display text-[15px] font-semibold text-text">
                {group.title}
              </p>
              <Badge
                className={cn(
                  'whitespace-nowrap',
                  group.tone === 'blue' && 'bg-blue-deep text-bg',
                  group.tone === 'green' && 'bg-green-deep text-bg',
                )}
              >
                {group.tag}
              </Badge>
            </div>
            <div className="mt-1.5">
              {group.items.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => onPick(item)}
                  className="block w-full rounded-lg px-2.5 py-2 text-left text-[14px] font-medium text-text2 hover:bg-surface hover:text-text"
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <p className="mt-5 max-w-[620px] text-[13px] leading-[1.5] text-text2">
        Ассистент не увидит проекты и материалы, к которым у вас нет доступа, и не
        выполнит действие, на которое у вас нет прав, — вместо этого предложит, кого
        попросить.
      </p>
    </div>
  )
}
