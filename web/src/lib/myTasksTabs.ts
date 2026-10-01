/**
 * Вкладки «Моих задач» и разбор адреса страницы — вся логика без React.
 *
 * С 16.09 `/my` — единственный вход в личную работу: экран поглотил скрытый
 * проект «Личное», и страница личного проекта сюда редиректит. Отсюда шесть
 * вкладок вместо четырёх и три параметра в адресе, которые обязаны уживаться:
 * `?tab=` (вкладка), `?task=` (открытая карточка), `?new=personal` (фокус
 * строки создания из FAB). Правила их разбора живут ЗДЕСЬ, а не в эффектах
 * страницы: эффекты уже однажды начали затирать друг друга, а jsdom в проекте
 * нет — чистая функция единственное, что здесь вообще можно покрыть тестом.
 *
 * `?tab=`, а не `?view=`: второе занято типом представления на странице
 * проекта (список/доска/календарь), и одинаковые имена с разным смыслом в
 * соседних экранах читаются как ошибка.
 */

import { type DueWindow, type MyTasksFilters } from '@/hooks/useMyTasks'

/** Окна дедлайнов + два «пространства»: мои личные и мои поручения. */
export type MyTasksTab = DueWindow | 'personal' | 'assigned'

// Порядок и дефолт — просьба владельца 01.10: «Все» первой (просроченные,
// предстоящие, без срока и личные вперемешку, без выполненных), дальше по
// убыванию срочности, «пространства» — в конце. Ключ `personal` не менять:
// на `/my?tab=personal` ведут `taskLocation`, редирект личного проекта и FAB.
export const MY_TASKS_TABS: { key: MyTasksTab; label: string }[] = [
  { key: 'all', label: 'Все' },
  { key: 'today', label: 'Сегодня' },
  { key: 'overdue', label: 'Просрочено' },
  { key: 'upcoming', label: 'Предстоит' },
  { key: 'personal', label: 'Личное' },
  { key: 'assigned', label: 'Назначенные мной' },
]

const DEFAULT_TAB: MyTasksTab = 'all'

/** Вкладка-окно (её обслуживает `/me/tasks`), а не отдельная выборка. */
export function isDueWindowTab(tab: MyTasksTab): tab is DueWindow {
  return tab !== 'personal' && tab !== 'assigned'
}

/**
 * Параметры `/me/tasks` для вкладки-окна; `null` — вкладке запрос не нужен
 * («Личное» и «Назначенные мной» живут своими выборками).
 *
 * «Все» — без выполненных (владелец, 01.10): бэкенд принимает `done=false`,
 * а клиент до этого не слал `done` вовсе, и выполненные шли вперемешку с
 * живыми, зачёркнутые, причём выполненная с прошлым сроком уезжала в
 * группу «Сегодня». Правило одно на `/my` и панель «Главной»: ключ кэша у
 * них обязан совпадать, иначе два запроса одного и того же.
 */
export function myTasksWindowFilters(tab: MyTasksTab): MyTasksFilters | null {
  if (!isDueWindowTab(tab)) return null
  return tab === 'all' ? { due_window: 'all', done: false } : { due_window: tab }
}

/**
 * Группировать ли список по срокам.
 *
 * «Все» и «Предстоит»: во второе с 15.09 приходят задачи без срока, и без
 * заголовка «Без срока» они читались бы как хвост просроченного. Условие жило
 * скопированным в двух раскладках — здесь оно одно.
 */
export function isGroupedTab(tab: MyTasksTab): boolean {
  return tab === 'all' || tab === 'upcoming'
}

/**
 * Какая вкладка открыта по адресу.
 *
 * `?new=personal` (ссылка из FAB) означает «Личные» даже без `?tab=` — иначе
 * человек, нажавший «Личная задача», попадал бы на «Предстоит», где инпута
 * создания нет вовсе.
 *
 * `hasPersonal` — есть ли у человека личный проект: у principal без hub-роли
 * его не заводят, и вкладку показывать нечем.
 */
export function resolveMyTasksTab(
  params: URLSearchParams,
  opts: { hasPersonal: boolean },
): MyTasksTab {
  if (params.get('new') === 'personal') {
    return opts.hasPersonal ? 'personal' : DEFAULT_TAB
  }
  const raw = params.get('tab')
  const known = MY_TASKS_TABS.find((t) => t.key === raw)
  if (!known) return DEFAULT_TAB
  if (known.key === 'personal' && !opts.hasPersonal) return DEFAULT_TAB
  return known.key
}

/** Адрес новой вкладки. Дефолт в URL не пишем: у «Моих задач» он один и
 *  известен без данных (у `ProjectPage` с 01.10 иначе — там голый адрес
 *  значит «дефолт по колонкам», и вид пишется всегда). */
export function setMyTasksTab(params: URLSearchParams, tab: MyTasksTab): URLSearchParams {
  const next = new URLSearchParams(params)
  if (tab === DEFAULT_TAB) next.delete('tab')
  else next.set('tab', tab)
  // Смена вкладки закрывает карточку: она принадлежала строке, которой на
  // новой вкладке может не быть вовсе.
  next.delete('task')
  // `new` — одноразовый приказ «сфокусируй инпут», и после ухода с «Личных»
  // он вернул бы туда обратно на следующем рендере.
  next.delete('new')
  return next
}

/**
 * Снять `?new=personal`, не потеряв вкладку.
 *
 * Обязательно одним движением: удалить `new` и НЕ поставить `tab=personal`
 * значит вернуть человека на «Предстоит» сразу после того, как он попросил
 * создать личную задачу. Ошибку такого рода глазами не видно — отсюда тест.
 */
export function clearNewPersonalParams(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params)
  next.delete('new')
  next.set('tab', 'personal')
  return next
}

/**
 * Куда уводить со страницы СВОЕГО личного проекта.
 *
 * `?task=` переносим: по таким адресам ведут пуши, «Входящие» и ссылки из
 * вчерашних бандлов — потерять карточку при редиректе значит сломать их все.
 * Всё остальное (`?view=board`, фильтры `f_*`) выбрасываем: ни доски, ни
 * фильтров проекта у личного пространства больше нет.
 */
export function personalProjectRedirect(params: URLSearchParams): string {
  const next = new URLSearchParams()
  next.set('tab', 'personal')
  const task = params.get('task')
  if (task) next.set('task', task)
  return `/my?${next.toString()}`
}

/** Текст пустого состояния вкладки. */
export function myTasksEmptyText(tab: MyTasksTab): string {
  if (tab === 'overdue') return 'Нет просроченных — отлично!'
  if (tab === 'today') return 'На сегодня задач нет — и просроченных тоже.'
  if (tab === 'personal') return 'Личных задач пока нет.'
  if (tab === 'assigned') return 'Вы пока никому не ставили задач.'
  if (tab === 'all') return 'Задач пока нет — ни рабочих, ни личных.'
  return 'Здесь пока пусто.'
}
