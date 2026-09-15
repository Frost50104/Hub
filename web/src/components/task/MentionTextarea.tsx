import {
  forwardRef,
  useImperativeHandle,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type TextareaHTMLAttributes,
} from 'react'

import { Avatar } from '@/components/ui/Avatar'
import { Textarea } from '@/components/ui/Input'
import { useTenantMembers } from '@/hooks/useTenantMembers'
import { applyMention, mentionContext } from '@/lib/mentions'

interface MentionTextareaProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'onChange' | 'value'> {
  value: string
  onValueChange: (next: string) => void
}

/**
 * Textarea с попапом упоминаний.
 *
 * Разбор ввода — в чистом `lib/mentions.ts` (там же тесты): попап открывается
 * на кириллице и держится через один пробел, чтобы искать «Иван Петров», а не
 * только первое слово. До 14.09 класс символов был `[A-Za-z0-9._-]`, и первая
 * же русская буква закрывала попап — отсюда ОС «Хаб не находит человека».
 *
 * Вставляется `mention` — токен, который посчитал СЕРВЕР (`Имя_Фамилия` либо
 * логин, если ФИО неуникально). Клиент это решение не принимает: тёзки должны
 * разбираться в одном месте.
 */
export const MentionTextarea = forwardRef<HTMLTextAreaElement, MentionTextareaProps>(
  ({ value, onValueChange, onKeyDown, ...rest }, ref) => {
    const innerRef = useRef<HTMLTextAreaElement>(null)
    useImperativeHandle(ref, () => innerRef.current as HTMLTextAreaElement)

    const [query, setQuery] = useState<string | null>(null)
    const [anchorAt, setAnchorAt] = useState(0)
    const [selectedIdx, setSelectedIdx] = useState(0)

    const members = useTenantMembers(query ?? '')
    const list = members.data ?? []

    const onChangeInner = (e: ChangeEvent<HTMLTextAreaElement>) => {
      const text = e.target.value
      onValueChange(text)
      const ctx = mentionContext(text, e.target.selectionStart ?? 0)
      if (!ctx) {
        setQuery(null)
        return
      }
      setQuery(ctx.query)
      setAnchorAt(ctx.anchor)
      setSelectedIdx(0)
    }

    const insertMention = (token: string) => {
      const ta = innerRef.current
      if (!ta) return
      const cursor = ta.selectionStart ?? anchorAt + 1
      const { next, caret } = applyMention(value, anchorAt, cursor, token)
      onValueChange(next)
      setQuery(null)
      requestAnimationFrame(() => {
        ta.focus()
        ta.setSelectionRange(caret, caret)
      })
    }

    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (query !== null && list.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setSelectedIdx((i) => (i + 1) % list.length)
          return
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault()
          setSelectedIdx((i) => (i - 1 + list.length) % list.length)
          return
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault()
          insertMention(list[selectedIdx]!.mention)
          return
        }
        if (e.key === 'Escape') {
          e.preventDefault()
          setQuery(null)
          return
        }
      }
      onKeyDown?.(e)
    }

    return (
      <div className="relative">
        <Textarea
          ref={innerRef}
          value={value}
          onChange={onChangeInner}
          onKeyDown={handleKeyDown}
          {...rest}
        />
        {/* Пустую выдачу показываем ЯВНО: раньше попап просто исчезал, и со
            стороны человека это выглядело как «справочник не работает». */}
        {query !== null && (
          // Ниже lg попап встаёт НАД полем: на телефоне композер прижат к низу
          // листа, и выпадашка под ним уходила бы за клавиатуру.
          <div className="absolute bottom-full left-0 right-0 z-30 mb-1 max-h-60 overflow-y-auto rounded-lg border border-glass-border bg-bg p-1 shadow-glass lg:bottom-auto lg:top-full lg:mb-0 lg:mt-1">
            {list.length === 0 && (
              <p className="px-2 py-2 text-xs text-text2">
                {members.isFetching ? 'Ищем…' : 'Никого не нашли'}
              </p>
            )}
            {list.map((m, i) => (
              <button
                type="button"
                key={m.employee_id}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => insertMention(m.mention)}
                className={
                  'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left ' +
                  (i === selectedIdx ? 'bg-surface text-text' : 'text-text2 hover:bg-glass hover:text-text')
                }
              >
                <Avatar
                  employeeId={m.employee_id}
                  name={m.full_name}
                  email={m.email}
                  className="h-6 w-6 text-[12px]"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-text">
                    {m.full_name || m.email}
                  </p>
                  <p className="truncate text-xs text-text2">@{m.handle}</p>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    )
  },
)
MentionTextarea.displayName = 'MentionTextarea'
