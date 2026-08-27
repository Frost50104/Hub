import { type TaskStage } from './stages'

/**
 * Перестановка колонок доски после перетаскивания.
 *
 * Отдельной чистой функцией по двум причинам. Первая: vitest здесь без jsdom,
 * и всё, что живёт внутри компонента, тестами не покрывается вовсе. Вторая:
 * ручка ждёт ЦЕЛЕВОЙ ИНДЕКС (`PATCH /stages/{id}` сам сдвигает соседей), а
 * оптимистичный кэш обязан посчитать ровно то же, что посчитает сервер, —
 * иначе порядок на экране разойдётся с базой до следующего рефетча.
 */
export interface StageMove {
  /** Что двигаем. */
  stageId: string
  /** Куда: индекс в новом порядке, он же `position` для PATCH. */
  position: number
  /** Готовый порядок для оптимистичного кэша — `position` уже перенумерован. */
  next: TaskStage[]
}

/**
 * `null` — двигать нечего: бросили на себя, промахнулись мимо колонки или
 * список ещё не приехал. Вызывающий в этом случае не шлёт запрос.
 */
export function reorderStages(
  stages: readonly TaskStage[],
  activeId: string,
  overId: string,
): StageMove | null {
  if (activeId === overId) return null
  const from = stages.findIndex((s) => s.id === activeId)
  const to = stages.findIndex((s) => s.id === overId)
  if (from === -1 || to === -1) return null

  const next = stages.slice()
  const [moved] = next.splice(from, 1)
  if (!moved) return null
  next.splice(to, 0, moved)

  return {
    stageId: activeId,
    position: to,
    // Позиции непрерывные 0..N-1 — тот же инвариант, что держит сервер.
    next: next.map((s, i) => ({ ...s, position: i })),
  }
}

/** Порядок после переименования — для того же оптимистичного кэша. */
export function renameStage(
  stages: readonly TaskStage[],
  stageId: string,
  name: string,
): TaskStage[] {
  return stages.map((s) => (s.id === stageId ? { ...s, name } : s))
}
