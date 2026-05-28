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

interface MentionTextareaProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'onChange' | 'value'> {
  value: string
  onValueChange: (next: string) => void
}

/**
 * Textarea with `@handle` autocomplete popover.
 *
 * Watches the segment between `@` and the caret while it consists of
 * `[A-Za-z0-9._-]`, queries `/api/tenant/members?q=...`, shows suggestions.
 * Picking a suggestion replaces `@partial` with `@handle ` and re-focuses.
 *
 * Mentions are sent verbatim — backend re-parses them with the same regex
 * (`app/services/mention_parser.py`), so client and server stay in sync.
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

    const computeMentionContext = (text: string, cursor: number) => {
      let i = cursor - 1
      while (i >= 0 && /[A-Za-z0-9._-]/.test(text[i]!)) i--
      if (i < 0 || text[i] !== '@') return null
      // Only trigger if `@` is at start or preceded by whitespace —
      // matches the backend mention_parser boundary rule.
      if (i > 0 && /[\w]/.test(text[i - 1]!)) return null
      return { anchor: i, partial: text.slice(i + 1, cursor) }
    }

    const onChangeInner = (e: ChangeEvent<HTMLTextAreaElement>) => {
      const text = e.target.value
      onValueChange(text)
      const ctx = computeMentionContext(text, e.target.selectionStart ?? 0)
      if (!ctx) {
        setQuery(null)
        return
      }
      setQuery(ctx.partial)
      setAnchorAt(ctx.anchor)
      setSelectedIdx(0)
    }

    const insertMention = (handle: string) => {
      const ta = innerRef.current
      if (!ta) return
      const cursor = ta.selectionStart ?? anchorAt + 1
      const before = value.slice(0, anchorAt)
      const after = value.slice(cursor)
      const inserted = `@${handle} `
      const next = before + inserted + after
      onValueChange(next)
      setQuery(null)
      requestAnimationFrame(() => {
        const pos = before.length + inserted.length
        ta.focus()
        ta.setSelectionRange(pos, pos)
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
          insertMention(list[selectedIdx]!.handle)
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
        {query !== null && list.length > 0 && (
          <div className="glass absolute left-0 right-0 z-30 mt-1 max-h-60 overflow-y-auto p-1 shadow-glass">
            {list.map((m, i) => (
              <button
                type="button"
                key={m.employee_id}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => insertMention(m.handle)}
                className={
                  'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left ' +
                  (i === selectedIdx ? 'bg-surface text-text' : 'text-text2 hover:bg-glass hover:text-text')
                }
              >
                <Avatar
                  name={m.full_name}
                  email={m.email}
                  className="h-6 w-6 text-[10px]"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-text">
                    {m.full_name || m.email}
                  </p>
                  <p className="truncate text-xs text-text3">@{m.handle}</p>
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
