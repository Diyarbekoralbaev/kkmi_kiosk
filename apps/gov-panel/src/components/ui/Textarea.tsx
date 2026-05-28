import { forwardRef, type TextareaHTMLAttributes } from 'react'
import { cn } from './cn'

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea({ invalid, className, ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(
          'w-full rounded-lg border bg-card px-3 py-2 text-sm text-ink placeholder:text-ink-muted/60',
          'transition focus:outline-none focus:ring-2 disabled:opacity-50 disabled:bg-surface resize-y',
          invalid
            ? 'border-danger focus:border-danger focus:ring-danger/20'
            : 'border-line focus:border-brand focus:ring-brand/20',
          className,
        )}
        aria-invalid={invalid || undefined}
        {...rest}
      />
    )
  },
)
