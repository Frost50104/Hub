/**
 * Гусь — свой inline-SVG (бренд-ассетов UPPETIT в репо нет). Тело —
 * `currentColor`, клюв и лапы — оранжевый плейсхолдер бренда. Интерфейс
 * компонента останется тем же при замене на клиентский ассет.
 */
export function GooseIcon({ size = 32, pose = 'run', className }: { size?: number; pose?: 'idle' | 'run'; className?: string }) {
  const legs =
    pose === 'run' ? (
      <>
        <path d="M14 25 L11 31" />
        <path d="M18 25 L21 31" />
      </>
    ) : (
      <>
        <path d="M15 25 L15 31" />
        <path d="M18 25 L18 31" />
      </>
    )
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      className={className}
      style={{ display: 'block', overflow: 'visible' }}
    >
      {/* тело */}
      <ellipse cx="15" cy="20" rx="10" ry="6" fill="currentColor" />
      {/* крыло */}
      <path d="M8 19 Q14 13 21 18 Q15 22 8 19 Z" fill="currentColor" opacity="0.55" />
      {/* хвост */}
      <path d="M5 18 L1 15 L6 21 Z" fill="currentColor" />
      {/* шея */}
      <path d="M22 18 Q26 14 25 8" stroke="currentColor" strokeWidth="3.2" fill="none" strokeLinecap="round" />
      {/* голова */}
      <circle cx="25.5" cy="7" r="3.2" fill="currentColor" />
      {/* клюв */}
      <path d="M28 6.2 L32 7.4 L28 8.6 Z" fill="rgb(var(--race-primary))" />
      {/* глаз */}
      <circle cx="26.3" cy="6.3" r="0.7" fill="rgb(var(--bg))" />
      {/* лапы */}
      <g stroke="rgb(var(--race-primary))" strokeWidth="1.8" strokeLinecap="round" fill="none">
        {legs}
      </g>
    </svg>
  )
}
