import { useEffect, type RefObject } from 'react'

/**
 * «Новая задача» из сайдбара — одна точка входа с инлайн-полем списка:
 * на странице проекта кнопка ставит курсор в то же поле «+ Новая задача»,
 * а не открывает второй способ создать задачу. Вне проекта — диалог.
 *
 * Механика — событие на window: сайдбар не знает, какой список смонтирован.
 * Первое поле, которое откликнулось, помечает событие `preventDefault`, чтобы
 * остальные (секции ниже, колонки доски) не перехватывали фокус.
 */
const EVENT = 'hub:quick-create'

interface QuickCreateDetail {
  projectId: string
}

/** true — кто-то поймал событие и сфокусировал поле; false — открывайте диалог. */
export function requestInlineCreate(projectId: string): boolean {
  const ev = new CustomEvent<QuickCreateDetail>(EVENT, {
    detail: { projectId },
    cancelable: true,
  })
  window.dispatchEvent(ev)
  return ev.defaultPrevented
}

export function useInlineCreateTarget(
  ref: RefObject<HTMLInputElement | null>,
  projectId: string,
  enabled: boolean,
): void {
  useEffect(() => {
    if (!enabled) return undefined
    const onEvent = (e: Event) => {
      const ev = e as CustomEvent<QuickCreateDetail>
      if (ev.defaultPrevented || ev.detail?.projectId !== projectId) return
      const el = ref.current
      if (!el) return
      ev.preventDefault()
      el.scrollIntoView({ block: 'nearest' })
      el.focus()
    }
    window.addEventListener(EVENT, onEvent)
    return () => window.removeEventListener(EVENT, onEvent)
  }, [ref, projectId, enabled])
}
