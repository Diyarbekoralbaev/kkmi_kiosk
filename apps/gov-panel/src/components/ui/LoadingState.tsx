import { cn } from './cn'

interface LoadingStateProps {
  label?: string
  className?: string
}

export function LoadingState({
  label = 'Yuklanmoqda...',
  className,
}: LoadingStateProps) {
  return (
    <div
      className={cn(
        'flex items-center justify-center gap-3 px-6 py-12 text-sm text-ink-muted',
        className,
      )}
    >
      <span
        aria-hidden
        className="h-4 w-4 animate-spin rounded-full border-2 border-brand/30 border-t-brand"
      />
      <span>{label}</span>
    </div>
  )
}
