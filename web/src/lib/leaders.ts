import type { Leader, LeaderMe, Leaders } from './stats'

/** Три колонки «Команды за 30 дней» — порядок фиксирован (владелец, 01.10). */
export type LeaderColumn = 'completed' | 'created' | 'overdue'

export interface LeaderColumnDef {
  key: LeaderColumn
  /** Заголовок колонки на десктопе. */
  title: string
  /** Подпись сегмента на телефоне — короче. */
  short: string
  /** Пустая колонка — текст вместо строк, нулей не рисуем. */
  empty: string
  /** Пилюля места: амбер у двух позитивных колонок, красная у просрочки
   *  («красный — только просрочка и ошибка», без «медалей»). */
  tone: 'amber' | 'danger'
}

export const LEADER_COLUMNS: LeaderColumnDef[] = [
  {
    key: 'completed',
    title: 'Выполнили',
    short: 'Выполнили',
    empty: 'Пока никто не закрыл задач за 30 дней.',
    tone: 'amber',
  },
  {
    key: 'created',
    title: 'Создали',
    short: 'Создали',
    empty: 'Пока никто не заводил задач за 30 дней.',
    tone: 'amber',
  },
  {
    // «Сейчас» в заголовке: это состояние, а не «за месяц».
    key: 'overdue',
    title: 'Просрочено сейчас',
    short: 'Просрочено',
    empty: 'Просроченных нет — отлично!',
    tone: 'danger',
  },
]

export function leaderColumn(key: LeaderColumn): LeaderColumnDef {
  return LEADER_COLUMNS.find((c) => c.key === key)!
}

/** «5-е место» — у «места» средний род, окончание одно на все числа. */
export function placeLabel(rank: number): string {
  return `${rank}-е место`
}

/**
 * Строка под колонкой про меня. В тройке — `null`: строка и так помечена
 * «— это вы». Ноль (`me === null`) — честное «пока не в рейтинге», у просрочки
 * ноль — хорошая новость.
 */
export function meLine(
  column: LeaderColumn,
  me: LeaderMe | null | undefined,
  rows: Leader[],
  myId: string | undefined,
): string | null {
  if (myId && rows.some((r) => r.employee_id === myId)) return null
  if (!me) {
    if (column === 'overdue') return 'У вас просроченных нет'
    if (column === 'created') return 'Вы пока не заводили задач за 30 дней'
    return 'Вы пока не закрывали задач за 30 дней'
  }
  return `Вы — ${placeLabel(me.rank)} · ${me.count}`
}

/** Колонка ответа по ключу — один доступ вместо трёх условий в разметке. */
export function columnRows(data: Leaders, column: LeaderColumn): Leader[] {
  return data[column]
}

export function columnMe(data: Leaders, column: LeaderColumn): LeaderMe | null {
  return data.me[column]
}
