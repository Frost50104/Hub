/**
 * Действия с папкой проектов — общая логика сайдбара и `/projects`.
 *
 * Правило переименования у папки общее с колонкой доски и живёт в
 * `lib/renameDraft.ts`; здесь остаётся то, что есть только у папки.
 */

/** Текст диалога удаления: главное — что проекты выживут. */
export function folderDeleteWarning(projectCount: number): string {
  if (projectCount === 0) return 'Папка пуста.'
  return `Проекты (${projectCount}) останутся — они переедут в «Без папки».`
}
