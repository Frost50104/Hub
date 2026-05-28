import { type HTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

interface AvatarProps extends HTMLAttributes<HTMLDivElement> {
  name: string | null | undefined
  email?: string | null
}

function initials(name: string | null | undefined, email: string | null | undefined): string {
  const source = name?.trim() || email?.split('@')[0] || '?'
  const parts = source.split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]?.toUpperCase() ?? '').join('') || '?'
}

export function Avatar({ name, email, className, ...props }: AvatarProps) {
  return (
    <div
      className={cn(
        'inline-flex h-8 w-8 select-none items-center justify-center rounded-full bg-amber/20 text-xs font-medium uppercase text-amber',
        className,
      )}
      title={name || email || undefined}
      {...props}
    >
      {initials(name, email)}
    </div>
  )
}
