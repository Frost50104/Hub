import { X } from 'lucide-react'
import {
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'

import { MobileDateCell } from '@/components/ui/MobileDateCell'
import { NativeDateInput } from '@/components/ui/NativeDateInput'
import { cn } from '@/lib/cn'
import { commitAction, type DateDraft, syncDraft, withDay } from '@/lib/dateDraft'
import {
  type DateTimeField,
  type DateTimePatch,
  type DateTimeValue,
  dateTimePatch,
  splitDateTime,
} from '@/lib/taskDateTime'

/** Дата/время — значение поля, а не статус: силуэт чипа 26px, не бейджа. */
export const DATE_CHIP =
  'inline-flex h-[26px] items-center rounded-md bg-surface px-2 font-body text-[12px] font-semibold text-text2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 disabled:cursor-default'

/**
 * Escape в поле с несохранённым вводом откатывает ввод, а не закрывает
 * карточку. Radix ловит Escape на document в фазе захвата — раньше, чем
 * `onKeyDown` поля, — поэтому карточка спрашивает редакторы через реестр в
 * своём `onEscapeKeyDown` (реестр передаётся пропом `escape`).
 */
export interface DraftEscapeRegistry {
  register: (handler: () => boolean) => () => void
  /** true — какой-то редактор откатил ввод, закрывать карточку не надо. */
  handle: () => boolean
}

export function createDraftEscapeRegistry(): DraftEscapeRegistry {
  const handlers = new Set<() => boolean>()
  return {
    register(handler) {
      handlers.add(handler)
      return () => handlers.delete(handler)
    },
    handle() {
      let handled = false
      for (const h of handlers) handled = h() || handled
      return handled
    },
  }
}

interface Props {
  field: DateTimeField
  iso: string | null
  hasTime: boolean | undefined
  readOnly: boolean
  variant: 'desktop' | 'mobile'
  /** Подпись поля для скринридера: «Срок», «Дата старта». */
  label: string
  onCommit: (patch: DateTimePatch) => void
  /** Классы даты — красный у просроченного срока. */
  dateClassName?: string
  /** Телефон: бейдж «−N дн» слева, вне зоны тапа. */
  badge?: ReactNode
  /** Десктоп: соседи в той же строке (текст просрочки, «Повтор»). */
  after?: ReactNode
  /** Реестр карточки для Escape (см. `createDraftEscapeRegistry`). */
  escape?: DraftEscapeRegistry
}

/**
 * Дата + необязательное время старта или срока в карточке задачи (0061).
 *
 * Черновик, а не сохранение на каждый `onChange`: набор с клавиатуры шлёт
 * промежуточные значения (год «2027» → `0002 → 0020 → 0202 → 2027`, время
 * «1530» → `15:03 → 15:30`, перенабор дня — пустую строку; замер в Chrome
 * 24.09), и каждое уходило PATCH-ем. Сохраняем пару «дата + время» ОДНИМ
 * запросом, когда фокус уходит из пары, по Enter, при смене задачи/закрытии
 * карточки (flush в cleanup) и при уходе со страницы (`pagehide`,
 * `visibilitychange`). Правило одно для мыши и тача: раскладку выбирает
 * ширина, а не способ ввода, и окно десктопа на 960px получает мобильные поля
 * с клавиатурой.
 *
 * Вызывающий ОБЯЗАН монтировать редактор с `key` по id задачи: панель
 * карточки не размонтируется, а «Назад» в браузере меняет задачу без blur —
 * cleanup ключевого экземпляра сохраняет черновик в ЕГО задачу, а не в новую.
 */
export function DateTimeEditor({
  field,
  iso,
  hasTime,
  readOnly,
  variant,
  label,
  onCommit,
  dateClassName,
  badge,
  after,
  escape,
}: Props) {
  const server = splitDateTime(iso, hasTime)
  const [draft, setDraftState] = useState<DateDraft>({ value: server, dirty: false })
  const [timeOpen, setTimeOpen] = useState(false)
  const timeRef = useRef<HTMLInputElement>(null)

  // Ref-зеркала для cleanup и слушателей окна: их замыкания живут дольше рендера.
  const draftRef = useRef(draft)
  const serverRef = useRef(server)
  serverRef.current = server
  const onCommitRef = useRef(onCommit)
  onCommitRef.current = onCommit

  const setDraft = useCallback((next: DateDraft) => {
    draftRef.current = next
    setDraftState(next)
  }, [])

  // Пришло новое с сервера — принимаем, только если человек ничего не набирает.
  useEffect(() => {
    const next = syncDraft(draftRef.current, serverRef.current)
    if (next !== draftRef.current) setDraft(next)
  }, [server.day, server.time, setDraft])

  const flush = useCallback(
    (badInput = false) => {
      const d = draftRef.current
      const action = commitAction(d, serverRef.current, badInput)
      if (action === 'none') {
        if (d.dirty) setDraft({ value: d.value, dirty: false })
        return
      }
      const patch = action === 'commit' ? dateTimePatch(field, d.value) : null
      if (!patch) {
        setDraft({ value: serverRef.current, dirty: false })
        return
      }
      setDraft({ value: d.value, dirty: false })
      onCommitRef.current(patch)
    },
    [field, setDraft],
  )

  // Смена задачи (ключ), закрытие карточки — сохраняем в СВОЮ задачу.
  useEffect(() => () => flush(), [flush])

  // Перезагрузка, `reloadFresh`, клик по пушу (`client.navigate`) — blur не наступит.
  useEffect(() => {
    const onHide = () => flush()
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') flush()
    }
    window.addEventListener('pagehide', onHide)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('pagehide', onHide)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [flush])

  useEffect(() => {
    if (!escape) return undefined
    return escape.register(() => {
      if (!draftRef.current.dirty) return false
      setDraft({ value: serverRef.current, dirty: false })
      setTimeOpen(false)
      return true
    })
  }, [escape, setDraft])

  useEffect(() => {
    if (timeOpen) timeRef.current?.focus()
  }, [timeOpen])

  const edit = (value: DateTimeValue) => setDraft({ value, dirty: true })
  const setDay = (day: string) => edit(withDay(draftRef.current.value, day))
  const setTime = (time: string) => edit({ day: draftRef.current.value.day, time })
  const clearTime = () => {
    edit({ day: draftRef.current.value.day, time: '' })
    setTimeOpen(false)
    flush()
  }
  // Явное снятие даты (ОС 25.09: «дату не удалить, только поменять»). Стереть
  // с клавиатуры по-прежнему можно только целиком: неполную дату черновик
  // откатывает — защита от опечатки, а не способ снять срок.
  const clearDate = () => {
    edit({ day: '', time: '' })
    setTimeOpen(false)
    flush()
  }

  const onGroupBlur = (e: FocusEvent<HTMLElement>) => {
    const next = e.relatedTarget
    if (next instanceof Node && e.currentTarget.contains(next)) return
    const input = e.target
    flush(input instanceof HTMLInputElement && input.validity.badInput)
    if (!draftRef.current.value.time) setTimeOpen(false)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === 'Enter' && e.target instanceof HTMLInputElement) {
      e.preventDefault()
      e.target.blur()
    }
  }

  const { day, time } = draft.value

  if (variant === 'mobile') {
    const showTime = !!day && (!!time || !readOnly)
    return (
      <span
        className="flex min-w-0 flex-1 items-center justify-end"
        onBlur={onGroupBlur}
        onKeyDown={onKeyDown}
      >
        <MobileDateCell
          value={day}
          ariaLabel={label}
          readOnly={readOnly}
          onChange={setDay}
          className={dateClassName}
        >
          {/* С временем на экране уже 360px бейдж не помещается (≈256px при
              ≈222 свободных, макет «4 · 320 px») — дата и так красная. */}
          {badge ? <span className={cn(time && 'max-[359px]:hidden')}>{badge}</span> : null}
        </MobileDateCell>
        {showTime && (
          <>
            <span aria-hidden className="h-5 w-px shrink-0 bg-hair" />
            <MobileDateCell
              type="time"
              grow={false}
              value={time}
              placeholder="+ время"
              ariaLabel={`Время: ${label}`}
              readOnly={readOnly}
              onChange={setTime}
              className={cn('pl-2.5', !time && 'text-[15px]')}
            />
            {time && !readOnly && (
              <button
                type="button"
                onClick={clearTime}
                aria-label={`Убрать время: ${label}`}
                className="flex h-[46px] w-11 shrink-0 items-center justify-center text-text2 active:bg-glass"
              >
                <X className="h-[18px] w-[18px]" strokeWidth={1.9} />
              </button>
            )}
          </>
        )}
      </span>
    )
  }

  return (
    <span
      className="flex flex-wrap items-center gap-2"
      onBlur={onGroupBlur}
      onKeyDown={onKeyDown}
    >
      <span className="inline-flex items-center gap-0.5">
        <NativeDateInput
          type="date"
          value={day}
          disabled={readOnly}
          aria-label={label}
          onChange={(e) => setDay(e.target.value)}
          className={cn(DATE_CHIP, dateClassName)}
        />
        {day && !readOnly && (
          <ClearButton label={`Убрать дату: ${label}`} title="Убрать дату" onClick={clearDate} />
        )}
      </span>
      {day && (time || timeOpen) ? (
        <span className="inline-flex items-center gap-0.5">
          <NativeDateInput
            ref={timeRef}
            type="time"
            value={time}
            disabled={readOnly}
            aria-label={`Время: ${label}`}
            onChange={(e) => setTime(e.target.value)}
            className={cn(DATE_CHIP, 'text-text')}
          />
          {!readOnly && (
            <ClearButton label={`Убрать время: ${label}`} title="Убрать время" onClick={clearTime} />
          )}
        </span>
      ) : day && !readOnly ? (
        <button
          type="button"
          onClick={() => setTimeOpen(true)}
          className={cn(DATE_CHIP, 'border border-dashed border-glass-border bg-transparent')}
        >
          + время
        </button>
      ) : null}
      {after}
    </span>
  )
}

/** × рядом с чипом даты или времени: снимает ровно то, у чего стоит. */
function ClearButton({ label, title, onClick }: { label: string; title: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={title}
      className="flex h-[26px] w-6 items-center justify-center rounded-md text-text2 hover:bg-glass hover:text-text"
    >
      <X className="h-3.5 w-3.5" strokeWidth={1.9} />
    </button>
  )
}
