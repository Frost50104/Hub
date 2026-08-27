/**
 * Форма материала библиотеки: что можно сохранить и что можно опубликовать.
 *
 * Правила вынесены из разметки, потому что второе из них — ЗЕРКАЛО серверного
 * условия (`change_status`: файловый материал без загруженной версии получает
 * 422 «Сначала загрузите файл»). Пока оно жило тернарником в JSX, кнопка
 * «Сохранить и опубликовать» была доступна всегда: материал создавался, а
 * публикация падала — то есть отказ приходил в конце пути, форма оставалась
 * открытой, и повторное нажатие заводило дубль.
 */

export interface MaterialFormState {
  title: string
  kind: 'file' | 'link'
  /** URL для kind='link'. */
  url: string
  /** Приложен ли файл в этой форме (для kind='file'). */
  hasFile: boolean
}

const URL_RE = /^https?:\/\/\S+$/

/** Достаточно ли заполнено, чтобы сохранить черновик. */
export function canSaveMaterial(s: MaterialFormState): boolean {
  if (s.title.trim().length === 0) return false
  return s.kind === 'link' ? URL_RE.test(s.url.trim()) : true
}

/** Можно ли сразу публиковать: у файлового материала обязателен файл. */
export function canPublishMaterial(s: MaterialFormState): boolean {
  if (!canSaveMaterial(s)) return false
  return !(s.kind === 'file' && !s.hasFile)
}
