import { createContext, useContext } from 'react'

/**
 * Что видеоблок редактора (React-представление ноды `video`) знает об уроке:
 * статус — для предупреждения при замене оригинала чистовиком в опубликованном
 * уроке, id — чтобы отличить «этот урок» от «ещё в N уроках» в ответе
 * `/learn/media/{id}/usage`. Провайдер стоит в `LessonEditor` над `RichEditor`:
 * React-ноды tiptap видят контекст обёртки редактора.
 */
export interface MediaToolsContextValue {
  lessonId: string | null
  lessonStatus: 'draft' | 'published' | null
}

export const MediaToolsContext = createContext<MediaToolsContextValue>({
  lessonId: null,
  lessonStatus: null,
})

export function useMediaToolsContext(): MediaToolsContextValue {
  return useContext(MediaToolsContext)
}
