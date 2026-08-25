/**
 * Инструкции по работе в Hub — что показать в «Учётной записи».
 *
 * Ссылки приходят ГОТОВЫМИ в `/api/me` (`guides`): они подписаны сервером,
 * потому что внутри инструкции — реальные экраны с ФИО коллег и адресами
 * точек, а Bearer в новой вкладке не работает. Забирать ссылку по клику
 * нельзя: `window.open` после `await` блокируют попап-фильтры, поэтому href
 * должен быть проставлен заранее.
 *
 * Здесь только чтение ответа сервера: правило «кому какая» живёт на бэкенде
 * (`services/guides.py::guides_for_role`), фронт его не дублирует.
 */

import type { Me } from '@/hooks/useMe'

export interface GuideLink {
  kind: string
  title: string
  url: string
}

/**
 * Строки раздела «Инструкция».
 *
 * Пустой массив — это «нечего показывать», и он же приходит от СТАРОГО
 * бэкенда в окне деплоя (поля `guides` в ответе просто нет): секцию в таком
 * случае не рисуем вовсе, а не показываем битую ссылку.
 */
export function guideRows(me: Me | undefined): GuideLink[] {
  const rows = me?.guides
  if (!Array.isArray(rows)) return []
  return rows.filter((r) => Boolean(r?.url && r?.title))
}
