import { type LessonContent } from '@/lib/learn'

/** Порог досмотра обязательного видео (сервер считает так же). */
export const WATCH_THRESHOLD = 0.9

export interface GateRowModel {
  label: string
  done: boolean
}

export const QUIZ_GATE_LABEL: Record<string, string> = {
  not_started: 'Сдать тест урока',
  in_progress: 'Закончить тест урока',
  failed: 'Сдать тест урока',
  pending_review: 'Тест на проверке — ждём результат',
  limit_exhausted: 'Лимит попыток исчерпан — обратитесь к руководителю',
  passed: 'Сдать тест урока',
}

/**
 * Чек-лист «Чтобы завершить урок»: контрольные вопросы, обязательные видео и
 * обязательный тест (состояние считает сервер — `quiz_state`, ОС 2026-08:
 * «тест не пройден, а пускает дальше»). Чистая функция — для vitest.
 */
export function gateRows(
  lesson: Pick<LessonContent, 'gate_blocks' | 'required_videos' | 'quiz_required' | 'quiz_state'>,
  answeredGates: Set<string>,
  videoCoverage: Record<string, number>,
): GateRowModel[] {
  const rows: GateRowModel[] = []
  if (lesson.gate_blocks.length) {
    const gatesDone = lesson.gate_blocks.filter((b) => answeredGates.has(b)).length
    rows.push({
      label:
        lesson.gate_blocks.length === 1
          ? 'Ответить на контрольный вопрос'
          : `Ответить на контрольные вопросы (${gatesDone} из ${lesson.gate_blocks.length})`,
      done: gatesDone >= lesson.gate_blocks.length,
    })
  }
  if (lesson.required_videos.length) {
    const videosDone = lesson.required_videos.filter(
      (m) => (videoCoverage[m] ?? 0) >= WATCH_THRESHOLD,
    ).length
    rows.push({
      label:
        lesson.required_videos.length === 1
          ? 'Досмотреть видео — минимум 90%'
          : `Досмотреть видео (${videosDone} из ${lesson.required_videos.length})`,
      done: videosDone >= lesson.required_videos.length,
    })
  }
  if (lesson.quiz_required) {
    rows.push({
      label: QUIZ_GATE_LABEL[lesson.quiz_state] ?? 'Сдать тест урока',
      done: lesson.quiz_state === 'passed',
    })
  }
  return rows
}

/** Тест обязателен и не сдан — сервер ответит 409, кнопку держим недоступной. */
export function quizBlocksCompletion(
  lesson: Pick<LessonContent, 'quiz_required' | 'quiz_state'>,
): boolean {
  return lesson.quiz_required && lesson.quiz_state !== 'passed'
}
