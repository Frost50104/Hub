import {
  BadgeCheck,
  BarChart3,
  BookOpen,
  Bot,
  Building2,
  ClipboardList,
  GraduationCap,
  Handshake,
  Inbox,
  Newspaper,
  ScrollText,
  ShoppingBag,
  Sparkles,
  Trophy,
  Users,
  Workflow,
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
  { to: '/learn/assistant', label: 'AI-помощник', icon: Bot },
  { to: '/learn/shifts', label: 'Биржа смен', icon: Handshake },
  { to: '/learn/assessments', label: 'Аттестации', icon: BadgeCheck },
  { to: '/inbox', label: 'Входящие', icon: Inbox, badge: true },
]

export const ADMIN_NAV: LearnNavItem[] = [
  { to: '/learn/admin/org', label: 'Оргструктура', icon: Building2 },
  { to: '/learn/admin/employees', label: 'Сотрудники', icon: Users },
  { to: '/learn/admin/review', label: 'Проверка тестов', icon: ClipboardList },
  { to: '/learn/admin/analytics', label: 'Аналитика', icon: BarChart3 },
  { to: '/learn/admin/automations', label: 'Автосценарии', icon: Workflow },
  { to: '/learn/admin/audit', label: 'Журнал', icon: ScrollText },
]

/** Разделы, уже представленные вкладками мобильного learn-таб-бара. */
const TAB_BAR_ROUTES = new Set(['/learn', '/learn/courses', '/inbox'])

/** Содержимое мобильного sheet'а «Меню» — всё из LEARN_NAV, чего нет в таб-баре. */
export const LEARN_MENU_ITEMS = LEARN_NAV.filter((i) => !TAB_BAR_ROUTES.has(i.to))
