import { useState } from 'react'
import { cn } from './cn'

type Tone = 'brand' | 'accent'

interface AvatarProps {
  src?: string | null
  name?: string | null
  size?: number
  tone?: Tone
  className?: string
}

const toneBg: Record<Tone, string> = {
  brand: 'bg-brand',
  accent: 'bg-accent-dark',
}

function initials(name?: string | null): string {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]?.toUpperCase() ?? '').join('') || '?'
}

export function Avatar({
  src,
  name,
  size = 44,
  tone = 'brand',
  className,
}: AvatarProps) {
  const [failed, setFailed] = useState(false)
  const showImage = !!src && !failed
  const dim = { width: size, height: size }
  const fontSize = Math.max(12, Math.round(size * 0.36))

  return (
    <div
      className={cn(
        'inline-flex shrink-0 items-center justify-center overflow-hidden rounded-pill text-white font-semibold',
        toneBg[tone],
        className,
      )}
      style={dim}
    >
      {showImage ? (
        <img
          src={src!}
          alt={name ?? ''}
          width={size}
          height={size}
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <span style={{ fontSize }}>{initials(name)}</span>
      )}
    </div>
  )
}
