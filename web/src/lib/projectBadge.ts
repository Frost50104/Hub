/**
 * Бейдж проекта: приоритет источников, палитра эмодзи, проверка файла.
 *
 * Чистый модуль — vitest здесь без jsdom, и компонент покрыть нечем, а
 * ломается именно эта логика (см. `lib/personalTasks.ts`, `lib/taskGrid.ts`).
 */

/** Что рисовать в квадрате. Картинка бьёт эмодзи, эмодзи бьёт буквы. */
export type ProjectBadge =
  | { kind: 'image'; url: string }
  | { kind: 'emoji'; emoji: string }
  | { kind: 'letters'; letters: string }

export interface ProjectBadgeSource {
  key: string
  is_favorite: boolean
  /** Опциональны: старый бэкенд в окне деплоя этих полей не отдаёт. */
  badge_emoji?: string | null
  badge_url?: string | null
}

export function resolveProjectBadge(project: ProjectBadgeSource): ProjectBadge {
  if (project.badge_url) return { kind: 'image', url: project.badge_url }
  const emoji = project.badge_emoji?.trim()
  if (emoji) return { kind: 'emoji', emoji }
  return { kind: 'letters', letters: project.key.slice(0, 2).toUpperCase() }
}

/**
 * Палитра быстрого выбора. Сетка `grid-cols-8`, поэтому длина кратна восьми —
 * иначе последний ряд рваный.
 *
 * Полную библиотеку не тащим: `emoji-mart` это ~200 КБ данных, а страница
 * проекта уже грузит дашборд через `lazy()` именно ради веса. Модель
 * «фиксированный набор в lib + серверная валидация» в приложении уже принята —
 * см. `REACTION_EMOJIS` в `lib/learn.ts`.
 */
export const PROJECT_EMOJI = [
  // работа и документы
  '📋', '📁', '🗂️', '📊', '📈', '🧾', '📝', '🗒️',
  // продукт и разработка
  '🚀', '🛠️', '⚙️', '🧪', '💡', '🧩', '🖥️', '📱',
  // места и логистика
  '🏪', '🏭', '🚚', '📦', '🏗️', '🗺️', '🧭', '🏢',
  // люди
  '👥', '🧑‍🍳', '🧑‍💼', '🤝', '🎓', '📣', '☎️', '💬',
  // еда и напитки
  '☕', '🍽️', '🥐', '🍕', '🥗', '🍰', '🧁', '🍹',
  // деньги и статусы
  '💰', '💳', '📉', '🎯', '✅', '⏳', '🔥', '⭐',
  // прочее
  '🎨', '🎬', '🎧', '🔍', '🔒', '🌱', '❄️', '🎉',
] as const

/**
 * Первый графемный кластер строки, если он эмодзи; иначе null.
 *
 * `Intl.Segmenter` обязателен: наивный `[...str][0]` разваливает ZWJ-семьи
 * (👨‍👩‍👧‍👦 стал бы одним 👨) и флаги. Зеркалит серверный валидатор
 * `app/schemas/project.py` — правило одно, но проверяется дважды: клиент,
 * чтобы не слать заведомый 422, и сервер, потому что клиенту верить нельзя.
 */
export function normalizeProjectEmoji(raw: string): string | null {
  const trimmed = raw.trim()
  if (!trimmed) return null
  const segmenter = new Intl.Segmenter('ru', { granularity: 'grapheme' })
  const first = segmenter.segment(trimmed)[Symbol.iterator]().next()
  if (first.done) return null
  const cluster = first.value.segment
  // \p{Extended_Pictographic} не покрывает флаги: они собраны из regional
  // indicators, у которых своё свойство.
  if (!/\p{Extended_Pictographic}|\p{Regional_Indicator}/u.test(cluster)) return null
  return cluster
}

/** MIME, которые принимает ручка бейджа. Зеркало `BADGE_MIME_EXT` на сервере. */
export const BADGE_ACCEPT = 'image/png,image/jpeg,image/webp'
const BADGE_MIME = ['image/png', 'image/jpeg', 'image/webp']
/** 512 КБ — зеркало `BADGE_MAX_BYTES`. */
export const BADGE_MAX_BYTES = 512 * 1024

/**
 * Сообщение об ошибке или null. Параметр структурный, а не `File`, — иначе
 * функция не запустится в node, где нет File.
 */
export function projectBadgeFileError(file: { type: string; size: number }): string | null {
  if (!BADGE_MIME.includes(file.type)) return 'Бейдж — картинка PNG, JPG или WebP'
  if (file.size > BADGE_MAX_BYTES) {
    return `Картинка больше ${Math.round(BADGE_MAX_BYTES / 1024)} КБ — уменьшите её`
  }
  return null
}
