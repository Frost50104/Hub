const COLORS = ['rgb(var(--race-gold))', 'rgb(var(--race-primary))', 'rgb(var(--green))', 'rgb(var(--text))']

/** 12 частиц CSS-конфетти для гуся на 400 клетках. */
export function RaceConfetti() {
  return (
    <span className="race-confetti pointer-events-none absolute inset-0" aria-hidden="true">
      {Array.from({ length: 12 }, (_, i) => (
        <span
          key={i}
          style={{
            ['--i' as string]: i,
            ['--dx' as string]: `${(i % 2 ? 1 : -1) * (6 + (i * 5) % 22)}px`,
            background: COLORS[i % COLORS.length],
          }}
        />
      ))}
    </span>
  )
}
