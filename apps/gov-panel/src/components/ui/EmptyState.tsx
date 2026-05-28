import type { ReactNode } from 'react'
import { cn } from './cn'

interface EmptyStateProps {
  icon?: ReactNode
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-card border border-dashed border-line bg-card/50 px-6 py-14 text-center',
        className,
      )}
    >
      {icon && (
        <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-brand/10 text-brand">
          {icon}
        </div>
      )}
      <div className="text-base font-semibold text-ink">{title}</div>
      {description && (
        <div className="mt-1 max-w-md text-sm text-ink-muted">{description}</div>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
