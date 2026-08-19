import { ArrowDown, ArrowUp, Check } from 'lucide-react'

import { cn } from '@/lib/cn'
import { type QuizSnapshotQuestion } from '@/lib/learn'

/**
 * Формы ответа по типам вопроса (Ф3b). Контракты значений сохранены:
 * single — индекс, multi — массив индексов, match — массив правых индексов
 * по позициям левых, order — массив индексов в выбранном порядке,
 * open — строка.
 *
 * Перетаскивания нет нигде: одной рукой в смене оно не работает.
 */

const ROW =
  'flex min-h-[52px] w-full items-center gap-3 rounded-xl border px-3.5 text-left text-[16px] font-medium transition-colors'
const MARK = 'flex h-[26px] w-[26px] shrink-0 items-center justify-center text-xs font-bold'

function OptionRow({
  label,
  picked,
  square,
  onClick,
}: {
  label: string
  picked: boolean
  /** Квадратная метка = «можно выбрать несколько»: форма, а не подпись. */
  square?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        ROW,
        picked ? 'border-amber bg-amber/[0.08] text-text' : 'border-hair bg-tint text-text',
      )}
    >
      <span
        className={cn(
          MARK,
          square ? 'rounded-[7px]' : 'rounded-full',
          picked
            ? 'bg-amber text-on-amber'
            : 'border border-glass-border text-transparent',
        )}
      >
        <Check className="h-3.5 w-3.5" strokeWidth={3} />
      </span>
      {label}
    </button>
  )
}

export function QuizAnswer({
  question,
  value,
  onChange,
}: {
  question: QuizSnapshotQuestion
  value: unknown
  onChange: (v: unknown) => void
}) {
  switch (question.qtype) {
    case 'single': {
      const options = question.options.options ?? []
      return (
        <div className="flex flex-col gap-2">
          {options.map((option, i) => (
            <OptionRow
              key={i}
              label={option}
              picked={value === i}
              onClick={() => onChange(i)}
            />
          ))}
        </div>
      )
    }

    case 'multi': {
      const options = question.options.options ?? []
      const picked = new Set(Array.isArray(value) ? (value as number[]) : [])
      return (
        <div className="flex flex-col gap-2">
          {options.map((option, i) => (
            <OptionRow
              key={i}
              label={option}
              square
              picked={picked.has(i)}
              onClick={() => {
                const next = new Set(picked)
                if (next.has(i)) next.delete(i)
                else next.add(i)
                onChange([...next].sort((a, b) => a - b))
              }}
            />
          ))}
        </div>
      )
    }

    case 'match':
      return <MatchAnswer question={question} value={value} onChange={onChange} />

    case 'order': {
      const items = question.options.items ?? []
      const order = Array.isArray(value) ? (value as number[]) : items.map((_, i) => i)
      const move = (from: number, delta: number) => {
        const to = from + delta
        if (to < 0 || to >= order.length) return
        const next = [...order]
        const tmp = next[from]!
        next[from] = next[to]!
        next[to] = tmp
        onChange(next)
      }
      return (
        <div className="flex flex-col gap-2">
          {order.map((itemIdx, pos) => (
            <div
              key={itemIdx}
              className="flex min-h-[52px] items-center gap-3 rounded-xl border border-hair bg-tint px-3 py-2"
            >
              <span className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-lg bg-amber font-display text-xs font-bold text-on-amber lg:h-7 lg:w-7">
                {pos + 1}
              </span>
              <span className="min-w-0 flex-1 text-[16px] text-text">{items[itemIdx]}</span>
              {/* Кнопки рядом по горизонтали: тап-таргет считается по каждой,
                  а промах по «выше» двигал бы шаг в обратную сторону. */}
              <span className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  aria-label="Выше"
                  disabled={pos === 0}
                  onClick={() => move(pos, -1)}
                  className="flex h-11 w-11 items-center justify-center rounded-lg text-text2 hover:bg-surface hover:text-text disabled:opacity-30 lg:h-[34px] lg:w-[34px]"
                >
                  <ArrowUp className="h-[18px] w-[18px]" />
                </button>
                <button
                  type="button"
                  aria-label="Ниже"
                  disabled={pos === order.length - 1}
                  onClick={() => move(pos, 1)}
                  className="flex h-11 w-11 items-center justify-center rounded-lg text-text2 hover:bg-surface hover:text-text disabled:opacity-30 lg:h-[34px] lg:w-[34px]"
                >
                  <ArrowDown className="h-[18px] w-[18px]" />
                </button>
              </span>
            </div>
          ))}
        </div>
      )
    }

    case 'open':
      return (
        <div className="flex flex-col gap-2">
          <textarea
            value={typeof value === 'string' ? value : ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Например: вкус становится горьким и вяжущим, крема тёмная и быстро оседает…"
            className="h-[150px] w-full rounded-xl border border-glass-border bg-tint px-3.5 py-3 text-[16px] leading-[1.6] text-text placeholder:text-text2 focus-visible:border-amber focus-visible:outline-none lg:h-[180px] lg:text-[17px]"
          />
          {/* Единственный тип, после которого результат может быть без баллов. */}
          <p className="text-[13px] leading-[1.45] text-text2">
            Ответ проверяет человек — балл придёт после проверки.
          </p>
        </div>
      )

    default:
      return null
  }
}

/** Сопоставление тапами: термин слева → определение справа, без перетаскивания. */
function MatchAnswer({
  question,
  value,
  onChange,
}: {
  question: QuizSnapshotQuestion
  value: unknown
  onChange: (v: unknown) => void
}) {
  const left = question.options.left ?? []
  const right = question.options.right ?? []
  const picks: (number | null)[] = left.map((_, i) =>
    Array.isArray(value) ? ((value as (number | null)[])[i] ?? null) : null,
  )
  const activeLeft = picks.findIndex((p) => p === null)

  const linkOf = (rightIdx: number) => picks.findIndex((p) => p === rightIdx)

  const assign = (rightIdx: number) => {
    const target = activeLeft >= 0 ? activeLeft : 0
    // Повторный выбор определения переносит связь, а не создаёт вторую.
    const next = picks.map((p) => (p === rightIdx ? null : p))
    next[target] = rightIdx
    onChange(next)
  }

  const clear = (leftIdx: number) => {
    const next = [...picks]
    next[leftIdx] = null
    onChange(next)
  }

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:gap-5">
      <div className="flex flex-1 flex-col gap-2">
        {left.map((item, i) => {
          const linked = picks[i] !== null && picks[i] !== undefined
          return (
            <button
              key={i}
              type="button"
              onClick={() => linked && clear(i)}
              className={cn(
                ROW,
                linked
                  ? 'border-green bg-green/[0.08] text-text'
                  : i === activeLeft
                    ? 'border-amber bg-amber/[0.08] text-text'
                    : 'border-hair bg-tint text-text',
              )}
            >
              <span
                className={cn(
                  MARK,
                  'rounded-full',
                  linked ? 'bg-green-deep text-bg' : 'bg-surface text-text2',
                )}
              >
                {i + 1}
              </span>
              {item}
            </button>
          )
        })}
      </div>

      <div className="flex flex-1 flex-col gap-2">
        <p className="text-xs font-bold uppercase tracking-[0.09em] text-text2">
          Определения
        </p>
        {right.map((item, j) => {
          const link = linkOf(j)
          const linked = link >= 0
          return (
            <button
              key={j}
              type="button"
              onClick={() => assign(j)}
              className={cn(
                ROW,
                linked
                  ? 'border-green bg-green/[0.08] text-text'
                  : 'border-dashed border-glass-border bg-transparent text-text',
              )}
            >
              <span
                className={cn(
                  MARK,
                  'rounded-full',
                  linked ? 'bg-green-deep text-bg' : 'bg-surface text-text2',
                )}
              >
                {linked ? link + 1 : '—'}
              </span>
              {item}
            </button>
          )
        })}
      </div>
    </div>
  )
}
