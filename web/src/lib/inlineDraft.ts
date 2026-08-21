/**
 * Черновик инлайн-создания («+ Новая задача», «+ Подзадача») — правила без
 * React, чтобы их можно было тестировать:
 *
 * - Enter и потеря фокуса коммитят непустой черновик; Escape отменяет;
 *   размонтирование коммитит (как Asana — ввёл и ушёл, задача создана).
 * - Черновик снимается СИНХРОННО до запроса: Enter→blur, blur→unmount или
 *   двойной Enter не дублируют задачу; при ошибке текст возвращается ТОЛЬКО
 *   если поле всё ещё пустое (пользователь мог начать следующую).
 * - Submit'ы идут цепочкой: следующий create уходит после ответа предыдущего —
 *   порядок ввода = порядок позиций, а Enter при этом не ждёт сервер.
 */
export interface InlineDraftOptions {
  submit: (title: string) => Promise<unknown>
  /** Зеркало значения для контролируемого инпута. */
  onChange: (value: string) => void
}

export interface InlineDraft {
  change: (value: string) => void
  enter: () => void
  blur: () => void
  escape: () => void
  unmount: () => void
  /** Текущий черновик (для тестов и отладки). */
  value: () => string
}

export function createInlineDraft({ submit, onChange }: InlineDraftOptions): InlineDraft {
  let draft = ''
  let queue: Promise<unknown> = Promise.resolve()

  const set = (v: string) => {
    draft = v
    onChange(v)
  }

  const commit = () => {
    const title = draft.trim()
    if (!title) {
      if (draft) set('')
      return
    }
    set('')
    queue = queue
      .then(() => submit(title))
      .catch(() => {
        // Ошибку показывает глобальный тост мутаций; текст возвращаем, только
        // если пользователь не начал печатать следующую задачу.
        if (!draft) set(title)
      })
  }

  return {
    change: set,
    enter: commit,
    blur: commit,
    escape: () => set(''),
    unmount: commit,
    value: () => draft,
  }
}
