/**
 * Что покажет строка контекста задачи — решение без React.
 *
 * Две функции и один источник истины. До 16.09 их было фактически две с
 * разными правилами: `hasTaskContext` отвечала спискам «резервировать ли под
 * строку полосу», а внутри компонента жила отдельная переменная `bare` с тем
 * же смыслом, но другим порядком условий. Расхождение таких пар всегда
 * кончается одинаково — полоса резервируется по одному правилу, рисуется по
 * другому, и высота строк в списке начинает скакать.
 *
 * Компонент в проекте не тестируется (vitest без jsdom), поэтому решение живёт
 * здесь, а `TaskContextLine` остаётся раскладкой — то же соглашение, что у
 * пары `inlineDraft.ts` ↔ `TaskInlineCreate.tsx`.
 */

import { type Label } from './labels'
import { type SubtaskStats, type Task } from './tasks'

export type TaskContextMode = 'auto' | 'plain'

export interface TaskContextOpts {
  labels?: Label[]
  subtasks?: SubtaskStats
  /** Имя проекта — подпись строки. */
  project?: string | null
  /** Имя колонки доски. */
  stage?: string | null
  /** `plain` — только подпись, без чипов (узкие списки «Главной»). */
  mode?: TaskContextMode
}

type CountedTask = Pick<
  Task,
  'comment_count' | 'attachment_count' | 'blocker_count' | 'recurrence'
>

/**
 * Есть ли ЧИПЫ: колонка, повтор, метки, подзадачи, счётчики.
 *
 * Отдельно от подписи проекта, потому что с 16.09 они показываются ВМЕСТЕ.
 * Раньше подпись была альтернативой чипам («fallback»), и на «Моих задачах»
 * это молча съедало имя проекта у каждой задачи с колонкой — а колонка есть
 * почти у всех: на проде 25 задач из 28 у самого загруженного человека. При
 * этом имя колонки почти ничего не различает («В работе» есть в 44 проектах),
 * а имя проекта — различает.
 */
export function hasChips(task: CountedTask, opts: TaskContextOpts = {}): boolean {
  if (opts.mode === 'plain') return false
  return (
    !!opts.stage ||
    !!task.recurrence ||
    (opts.labels?.length ?? 0) > 0 ||
    (opts.subtasks?.total ?? 0) > 0 ||
    (task.comment_count ?? 0) > 0 ||
    (task.attachment_count ?? 0) > 0 ||
    (task.blocker_count ?? 0) > 0
  )
}

/**
 * Будет ли строке контекста что показать — подпись проекта ИЛИ чипы.
 *
 * Зовут списки, чтобы решить, резервировать ли полосу 22px под строку. Тот же
 * ответ использует сам компонент, поэтому разойтись они не могут.
 */
export function hasTaskContext(task: CountedTask, opts: TaskContextOpts = {}): boolean {
  return !!opts.project || hasChips(task, opts)
}
