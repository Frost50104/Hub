import { Fragment } from 'react'

interface HighlightedSnippetProps {
  /** Server-rendered snippet with `‹‹...››` match markers around hits. */
  text: string | null | undefined
  className?: string
}

/**
 * Renders a `ts_headline` snippet from the backend, replacing the custom
 * `‹‹match››` markers with `<mark>` spans. We avoid `dangerouslySetInnerHTML`
 * because the source text comes from user-supplied descriptions/comments —
 * the marker pair is chosen specifically so it can't appear in normal Cyrillic
 * or Latin text, making the split safe.
 */
export function HighlightedSnippet({ text, className }: HighlightedSnippetProps) {
  if (!text) return null
  // Split on the closing marker first to preserve ordering, then peel the
  // opening marker out of each chunk. Empty chunks fall away naturally.
  const segments: { value: string; highlighted: boolean }[] = []
  let cursor = 0
  while (cursor < text.length) {
    const start = text.indexOf('‹‹', cursor)
    if (start === -1) {
      segments.push({ value: text.slice(cursor), highlighted: false })
      break
    }
    if (start > cursor) {
      segments.push({ value: text.slice(cursor, start), highlighted: false })
    }
    const end = text.indexOf('››', start + 2)
    if (end === -1) {
      // Unmatched opening marker → render the rest as plain.
      segments.push({ value: text.slice(start + 2), highlighted: false })
      break
    }
    segments.push({ value: text.slice(start + 2, end), highlighted: true })
    cursor = end + 2
  }

  return (
    <span className={className}>
      {segments.map((s, i) => (
        <Fragment key={i}>
          {s.highlighted ? (
            <mark className="rounded bg-amber/30 px-0.5 text-text">{s.value}</mark>
          ) : (
            s.value
          )}
        </Fragment>
      ))}
    </span>
  )
}
