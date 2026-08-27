/**
 * Что именно потеряется при удалении аттестации.
 *
 * Текст обязан быть честным до числа: удаление завершённой кампании уносит
 * каскадом тест, вопросы и ВСЕ попытки сотрудников — то есть саму запись о том,
 * кто аттестован. Общее «вы уверены?» такую цену не передаёт, а вернуть
 * удалённое нечем.
 */

import { plural } from '@/lib/typography'

export interface CampaignDeletionSource {
  status: 'draft' | 'active' | 'closed'
  question_count: number
  /** ВСЕ попытки по тесту, без пересечения с аудиторией. */
  attempt_count: number
}

export interface CampaignDeletion {
  /** Подпись диалога. */
  summary: string
  /** true — уйдут результаты людей; диалогу стоит быть строже. */
  losesResults: boolean
}

export function describeCampaignDeletion(c: CampaignDeletionSource): CampaignDeletion {
  const questions =
    c.question_count > 0 ? plural(c.question_count, 'вопрос', 'вопроса', 'вопросов') : null

  if (c.attempt_count > 0) {
    return {
      losesResults: true,
      summary:
        `Вместе с кампанией уйдут ${plural(c.attempt_count, 'попытка', 'попытки', 'попыток')} ` +
        'сотрудников — запись о том, кто прошёл аттестацию, исчезнет навсегда' +
        (questions ? `, как и ${questions}` : '') +
        '.',
    }
  }

  return {
    losesResults: false,
    summary: questions
      ? `Кампания удалится вместе с ${questions}. Проходить её никто не начинал — результатов нет.`
      : 'Кампания пуста: ни вопросов, ни попыток.',
  }
}

/** Вкладки экрана аттестаций. */
export type AssessmentView = 'my' | 'report' | 'manage'

/**
 * Какая вкладка открыта.
 *
 * `chosen === null` означает «человек ещё не выбирал» — и только тогда роль
 * решает за него: администратор приходит сюда управлять кампаниями, а кнопка
 * «+ Аттестация» живёт ровно на этой вкладке, поэтому на «Моих» он её просто
 * не находил.
 *
 * Дефолт считается ЗДЕСЬ, а не эффектом: `me` приезжает асинхронно, и
 * `useEffect` переключил бы вкладку уже после того, как человек выбрал сам.
 * Заодно функция отсекает вкладку, на которую прав больше нет (роль сняли,
 * пока экран открыт).
 */
export function resolveAssessmentView(
  chosen: AssessmentView | null,
  available: readonly AssessmentView[],
  isAdmin: boolean,
): AssessmentView {
  if (chosen && available.includes(chosen)) return chosen
  const byRole: AssessmentView = isAdmin ? 'manage' : 'my'
  return available.includes(byRole) ? byRole : 'my'
}
