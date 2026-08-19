import { useEffect, useState, type HTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

interface AvatarProps extends HTMLAttributes<HTMLDivElement> {
  name: string | null | undefined
  email?: string | null
  /** URL фото (auth-аватар); при 404/ошибке загрузки — фолбэк на инициалы. */
  src?: string | null
}

function initials(name: string | null | undefined, email: string | null | undefined): string {
  const source = name?.trim() || email?.split('@')[0] || '?'
  const parts = source.split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]?.toUpperCase() ?? '').join('') || '?'
}

export function Avatar({ name, email, src, className, ...props }: AvatarProps) {
  const [broken, setBroken] = useState(false)
  // Сбрасываем broken при смене src — иначе после relogin другим юзером
  // фото не появилось бы.
  useEffect(() => setBroken(false), [src])

  return (
    <div
      className={cn(
        // Заливка --av-fill НЕПРОЗРАЧНАЯ: полупрозрачная (amber/20) в стеке
        // просвечивала инициалы соседа. Краска --text, а не --amber: амбер на
        // амбер-тинте даёт 1,7:1 в светлой теме.
        'inline-flex h-6 w-6 select-none items-center justify-center overflow-hidden rounded-full bg-av-fill text-[12px] font-semibold uppercase text-text',
        className,
      )}
      title={name || email || undefined}
      {...props}
    >
      {src && !broken ? (
        <img
          src={src}
          alt=""
          className="h-full w-full object-cover"
          onError={() => setBroken(true)}
        />
      ) : (
        initials(name, email)
      )}
    </div>
  )
}
