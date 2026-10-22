import { Bell, CheckCircle2, GraduationCap, Home, Menu, Search, Sparkles } from 'lucide-react'

/**
 * Наборы вкладок мобильного таб-бара. Живут отдельно от `MobileBottomTabBar`,
 * чтобы состав проверялся vitest-ом без jsdom (компонент тянет хуки и axios).
 */

export type TabDef =
  | {
      kind: 'link'
      to: string
      label: string
      icon: typeof Home
      end?: boolean
      showUnreadDot?: boolean
    }
  | { kind: 'menu'; label: string; icon: typeof Home }

// Порядок — как в десктопном сайдбаре (Главная · Мои задачи · Ассистент ·
// Входящие), пятой — «Поиск» вместо поля поиска сайдбара. «Профиль» уехал
// аватаром в шапку мобильной «Главной» (22.10): без вкладки ассистент на
// телефоне был достижим только через «Обучение» → «Меню».
export const TASK_TABS: TabDef[] = [
  { kind: 'link', to: '/', label: 'Главная', icon: Home, end: true },
  { kind: 'link', to: '/my', label: 'Мои задачи', icon: CheckCircle2 },
  { kind: 'link', to: '/assistant', label: 'Ассистент', icon: Sparkles },
  { kind: 'link', to: '/inbox', label: 'Входящие', icon: Bell, showUnreadDot: true },
  { kind: 'link', to: '/search', label: 'Поиск', icon: Search },
]

// В learn-наборе пятая вкладка — «Меню» (sheet со всеми разделами);
// Профиль доступен строкой внутри sheet'а.
export const LEARN_TABS: TabDef[] = [
  { kind: 'link', to: '/learn', label: 'Витрина', icon: Sparkles, end: true },
  { kind: 'link', to: '/learn/courses', label: 'Обучение', icon: GraduationCap },
  { kind: 'link', to: '/inbox', label: 'Входящие', icon: Bell, showUnreadDot: true },
  { kind: 'link', to: '/search', label: 'Поиск', icon: Search },
  { kind: 'menu', label: 'Меню', icon: Menu },
]
