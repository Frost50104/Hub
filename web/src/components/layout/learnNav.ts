import {
  BadgeCheck,
  BarChart3,
  Bird,
  BookOpen,
  Bot,
  Building2,
  ClipboardList,
  GraduationCap,
  Handshake,
  Inbox,
  ListChecks,
  Newspaper,
  ScrollText,
  ShoppingBag,
  Sparkles,
  Star,
  Trophy,
  Users,
  Workflow,
  type LucideIcon,
} from 'lucide-react'

/**
 * Единый источник навигации learn-пространства: десктопный LearnSidebar и
 * мобильный LearnMenuSheet выводятся из одних массивов — списки и подсветка
 * вкладки «Меню» не могут разъехаться.
 */

export interface LearnNavItem {
  to: string
  label: string
  icon: typeof GraduationCap
  end?: boolean
  badge?: boolean
  soon?: boolean
  /** Модуль-остров: пункт показывается только при `me.features.<feature>`. */
  feature?: 'race'
}

/**
 * Название раздела курсов: сотруднику — «Моё обучение», управляющему —
 * «Учебные курсы» (ОС 19.08: «я не учусь, я веду курсы»). Один хелпер на все
 * точки — заголовок страницы, пункт меню и обратные ссылки обязаны называться
 * одинаково, иначе «назад» уводит в раздел с другим названием.
 *
 * Живёт здесь, а не в lib/learn.ts: тот модуль тянет за собой весь learn-API,
 * а этот импортируют лэйаут-компоненты из главного бандла.
 */
export function coursesSectionTitle(
  contentRole: 'none' | 'author' | 'publisher' | 'admin' | null | undefined,
  hubRole?: 'admin' | 'member' | 'viewer' | null,
): string {
  return canManageCourses(contentRole, hubRole) ? 'Учебные курсы' : 'Моё обучение'
}

/**
 * Кто ведёт курсы, а не проходит их. Зеркало серверного гейта
 * `require_content_role(..., "author")` (`app/api/courses.py`, `app/api/quizzes.py`):
 * hub-admin проходит всегда, из учебных ролей — author и publisher.
 *
 * ОДНА функция на заголовок раздела И на кнопки «Редактировать» со страниц
 * курса и урока: если правила разъедутся, человек с «Учебными курсами» в меню
 * не увидит кнопку правки — или увидит её и получит 403 при сохранении.
 */
export function canManageCourses(
  contentRole: 'none' | 'author' | 'publisher' | 'admin' | null | undefined,
  hubRole?: 'admin' | 'member' | 'viewer' | null,
): boolean {
  return (
    hubRole === 'admin' ||
    contentRole === 'author' ||
    contentRole === 'publisher' ||
    contentRole === 'admin'
  )
}

// Разделы включаются по мере этапов Ф1–Ф4; до готовности — «скоро» (disabled).
export const LEARN_NAV: LearnNavItem[] = [
  { to: '/learn', label: 'Витрина', icon: Sparkles, end: true },
  { to: '/learn/courses', label: 'Моё обучение', icon: GraduationCap },
  { to: '/learn/library', label: 'Библиотека', icon: BookOpen },
  { to: '/learn/news', label: 'Новости', icon: Newspaper },
  { to: '/learn/surveys', label: 'Опросы', icon: ClipboardList },
  { to: '/learn/products', label: 'Ассортимент', icon: ShoppingBag },
  { to: '/learn/rating', label: 'Рейтинг', icon: Trophy },
  // «Гусиная гонка» (0057): пункт живёт только при `me.features.race` —
  // фильтр в `learnNavFor`, сам массив статичен (из него выводятся
  // LEARN_MENU_ITEMS и подсветка таб-бара).
  { to: '/learn/race', label: 'Гонка', icon: Bird, feature: 'race' },
  { to: '/learn/favorites', label: 'Избранное', icon: Star },
  { to: '/assistant', label: 'AI-помощник', icon: Bot },
  { to: '/learn/shifts', label: 'Биржа смен', icon: Handshake },
  { to: '/learn/assessments', label: 'Аттестации', icon: BadgeCheck },
  { to: '/inbox', label: 'Входящие', icon: Inbox, badge: true },
]

/** «Управление» — один маршрут с сегментами (редизайн-2); вход виден всем, у кого ≥1 сегмент. */
export const ADMIN_NAV: LearnNavItem[] = [{ to: '/learn/admin', label: 'Управление', icon: Users }]

export type AdminSegment =
  | 'review'
  | 'analytics'
  | 'progress'
  | 'employees'
  | 'automations'
  | 'audit'
  | 'org'
  | 'race'

export const ADMIN_SEGMENTS: { key: AdminSegment; label: string; title: string; icon: LucideIcon }[] = [
  { key: 'review', label: 'Проверка', title: 'Проверка тестов', icon: ClipboardList },
  { key: 'analytics', label: 'Аналитика', title: 'Аналитика обучения', icon: BarChart3 },
  {
    key: 'progress',
    label: 'Прогресс сотрудников',
    title: 'Прогресс обучения по сотрудникам',
    icon: ListChecks,
  },
  { key: 'employees', label: 'Сотрудники', title: 'Сотрудники', icon: Users },
  { key: 'automations', label: 'Автосценарии', title: 'Автосценарии', icon: Workflow },
  { key: 'audit', label: 'Журнал', title: 'Журнал действий', icon: ScrollText },
  { key: 'org', label: 'Оргструктура', title: 'Оргструктура', icon: Building2 },
  { key: 'race', label: 'Гонка', title: 'Гусиная гонка', icon: Bird },
]

/**
 * Гейты — по сегментам, не по экрану, РОВНО как проверяет бэкенд:
 * - Проверка (`quizzes.py` review-queue) — publisher и hub-admin;
 * - Аналитика и Прогресс сотрудников (`learn_analytics.py`, общий гейт
 *   `_scope_profile_ids`) — publisher, hub-admin и скоуп магазинов
 *   (ТУ, франчайзи);
 * - Сотрудники/Автосценарии/Журнал/Оргструктура — только hub-admin.
 * Офис без publisher раньше видел обе вкладки и получал 403 (QA-0821 #24).
 */
export function adminSegmentsFor(me: {
  hub_role: string | null
  profile: { content_role: string; org_role: string } | null
} | undefined): AdminSegment[] {
  if (!me) return []
  const isAdmin = me.hub_role === 'admin'
  const publisher = ['publisher', 'admin'].includes(me.profile?.content_role ?? '')
  const storeScope = ['tu', 'franchisee_owner'].includes(me.profile?.org_role ?? '')
  const out: AdminSegment[] = []
  if (isAdmin || publisher) out.push('review')
  // `progress` строго ПОСЛЕ `analytics`: `LearnAdminPage` берёт первый
  // доступный сегмент как вкладку по умолчанию, и перестановка молча увела бы
  // ТУ с привычного экрана на новый.
  if (isAdmin || publisher || storeScope) out.push('analytics', 'progress')
  // «Гонка» — ПОСЛЕДНИМ и только admin: там живёт тумблер модуля, поэтому
  // сегмент виден даже при выключенной гонке (иначе включить неоткуда).
  if (isAdmin) out.push('employees', 'automations', 'audit', 'org', 'race')
  return out
}

/** Разделы, уже представленные вкладками мобильного learn-таб-бара. */
const TAB_BAR_ROUTES = new Set(['/learn', '/learn/courses', '/inbox'])

/** Содержимое мобильного sheet'а «Меню» — всё из LEARN_NAV, чего нет в таб-баре. */
export const LEARN_MENU_ITEMS = LEARN_NAV.filter((i) => !TAB_BAR_ROUTES.has(i.to))

/**
 * Пункты навигации с учётом модулей-островов: «Гонка» только при
 * `features.race`. Фильтр на рендере, а не мутация `LEARN_NAV`: из константы
 * выводятся `LEARN_MENU_ITEMS` и подсветка таб-бара при загрузке модуля.
 */
export function learnNavFor<T extends LearnNavItem>(
  items: T[],
  me: { features?: { race?: boolean } } | undefined,
): T[] {
  return items.filter((i) => !i.feature || me?.features?.[i.feature] === true)
}
