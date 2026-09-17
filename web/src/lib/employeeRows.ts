/**
 * Строки экрана «Сотрудники»: карточки и приглашения в ОДНОМ списке.
 *
 * ОС владельца 17.09: «"Приглашены в auth, ещё не приняли" всегда и на первом
 * месте, а доступные фильтры влияют только на показ после этого блока». Так и
 * было по построению — приглашения рисовались отдельным блоком над списком и
 * не проходили ни через поиск, ни через чипы.
 *
 * Отдельного блока больше нет. Приглашённые без карточки стали обычными
 * строками списка, а «приглашён(а)» — обычным фильтром. Выигрыш не только в
 * послушности фильтрам: из 69 строк прежнего блока 62 дублировали список под
 * собой (у этих людей карточка есть и стоит ниже с бейджем «Приглашён(а)»), и
 * семь по-настоящему нужных — те, у кого карточки нет вовсе, — в этой стене
 * терялись. Сервер теперь дубликаты и не отдаёт.
 *
 * Логика живёт здесь, а не в JSX, по той же причине, что и всегда в этом
 * репозитории: vitest бежит БЕЗ jsdom, и покрыть тестами можно только чистые
 * модули `lib/`. Экран обязан оставаться разметкой.
 */

import type { AuthFilter, AuthState } from './authState'
import { matchesAuthFilter } from './authState'
import type { AuthInvitation, EmployeeProfile } from './learn'

export type EmployeeRow =
  | { kind: 'profile'; id: string; name: string; profile: EmployeeProfile }
  | { kind: 'invitation'; id: string; name: string; invitation: AuthInvitation }

/**
 * Один компаратор на модуль, а не новый на каждое сравнение: `Intl.Collator`
 * дорог в конструировании, а сортируем мы список целиком на каждый ререндер.
 */
const collator = new Intl.Collator('ru', { sensitivity: 'base' })

/** Имя для показа и для сортировки: у приглашения ФИО может не быть вовсе. */
export function invitationName(inv: AuthInvitation): string {
  return inv.full_name?.trim() || inv.email
}

/**
 * Склеить карточки и приглашения в один отсортированный список.
 *
 * Сервер отдаёт в `invitations` только тех, у кого активной карточки НЕТ, —
 * поэтому дубли здесь не проверяем: проверка на клиенте означала бы вторую
 * копию правила, а правило уже стоит в SQL ручки (`NOT EXISTS`).
 */
export function mergeEmployeeRows(
  items: readonly EmployeeProfile[],
  invitations: readonly AuthInvitation[] = [],
): EmployeeRow[] {
  const rows: EmployeeRow[] = [
    ...items.map(
      (p): EmployeeRow => ({ kind: 'profile', id: p.id, name: p.full_name, profile: p }),
    ),
    ...invitations.map(
      (inv): EmployeeRow => ({
        kind: 'invitation',
        id: `inv:${inv.id}`,
        name: invitationName(inv),
        invitation: inv,
      }),
    ),
  ]
  return rows.sort((a, b) => collator.compare(a.name, b.name) || a.id.localeCompare(b.id))
}

/**
 * Фильтр по статусу учётки, общий для обоих видов строк.
 *
 * Чипы «Без учётки» и «Приглашены» НЕ пересекаются (17.09, ОС владельца: «под
 * чипом "Без учётки" и "Приглашены" одно и то же?» — так и было). Они отвечают
 * на разные вопросы: «никто не позвал» — работа для HR, «позвали, ждём» —
 * делать нечего. Строка-приглашение по определению второе.
 */
export function matchesRowFilter(filter: AuthFilter, row: EmployeeRow): boolean {
  if (row.kind === 'invitation') {
    // Строка-приглашение — это «позвали, ждём», а НЕ «никто не позвал».
    // Поэтому под «Без учётки» она не попадает: чипы не пересекаются.
    return filter === 'all' || filter === 'invited'
  }
  return matchesAuthFilter(filter, (row.profile.auth_state ?? null) as AuthState | null)
}

/**
 * Числа для всех чипов разом.
 *
 * Нужны не ради украшения: пустой чип показывать нельзя. Он выглядит как
 * работающий фильтр, а даёт пустой список — человек решает, что экран сломан.
 * Сегодня на проде пуст `no_account` (всех позвали), через неделю опустеет
 * `invited` (приглашения протухнут), и оба раза лишний чип будет врать.
 */
export function rowFilterCounts(
  rows: readonly EmployeeRow[],
): Record<Exclude<AuthFilter, 'all'>, number> {
  return {
    no_account: rows.filter((r) => matchesRowFilter('no_account', r)).length,
    not_logged_in: rows.filter((r) => matchesRowFilter('not_logged_in', r)).length,
    invited: rows.filter((r) => matchesRowFilter('invited', r)).length,
  }
}

/**
 * Подпись над списком.
 *
 * Три разных состояния, и путать их нельзя:
 * - фильтр включён → говорим, сколько отобрано из скольких, БЕЗ «уточните
 *   поиск»: человек сам сузил выдачу, советовать ему сузить её ещё раз глупо;
 * - фильтра нет, но показано меньше, чем есть → сработал предел добора страниц,
 *   и вот тут совет уместен (прежнее правило `employeeListCaption`);
 * - иначе просто «Всего: N».
 *
 * Считаем по ОТФИЛЬТРОВАННОМУ числу строк. Прежний экран передавал сюда
 * `items.length` до фильтра, а рисовал после — и под надписью «Всего: 264»
 * могло стоять три строки.
 */
export function employeeRowsCaption(
  shown: number,
  known: number,
  opts: { filtered: boolean },
): string {
  if (opts.filtered) return `Отобрано: ${shown} из ${known}`
  if (shown < known) {
    return `Показаны ${shown} из ${known} — уточните поиск, чтобы найти остальных`
  }
  return `Всего: ${known}`
}
