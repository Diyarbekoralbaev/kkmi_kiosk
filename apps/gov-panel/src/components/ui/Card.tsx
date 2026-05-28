import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from './cn'

type Padding = 'none' | 'tight' | 'normal' | 'loose'

interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  padding?: Padding
}

const pad: Record<Padding, string> = {
  none: '',
  tight: 'p-4',
  normal: 'p-6',
  loose: 'p-8',
}

export function Card({
  title,
  description,
  actions,
  padding = 'normal',
  className,
  children,
  ...rest
}: CardProps) {
  const hasHeader = !!(title || description || actions)
  return (
    <section
      className={cn(
        'rounded-card border border-line bg-card shadow-card',
        className,
      )}
      {...rest}
    >
      {hasHeader && (
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div>
            {title && (
              <h2 className="text-sm font-semibold uppercase tracking-widest text-ink-muted">
                {title}
              </h2>
            )}
            {description && (
              <p className="mt-1 text-sm text-ink-muted">{description}</p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(pad[padding])}>{children}</div>
    </section>
  )
}
