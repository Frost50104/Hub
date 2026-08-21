import { createContext, useContext } from 'react'

/**
 * «Управление» — один маршрут `/learn/admin?tab=` (редизайн-2): шесть прежних
 * страниц живут вкладками внутри `LearnAdminPage`. Вкладка не рисует свою
 * мобильную шапку и H1 — их владеет обёртка; страница узнаёт об этом через
 * контекст, а не через проп, потому что старые прямые маршруты остались
 * редиректами и компоненты по-прежнему самодостаточны.
 */
export const AdminEmbedContext = createContext(false)

export function useAdminEmbedded(): boolean {
  return useContext(AdminEmbedContext)
}
