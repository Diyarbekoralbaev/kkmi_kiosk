import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from './cn'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  leftIcon?: ReactNode
  rightSlot?: ReactNode
  invalid?: boolean
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { leftIcon, rightSlot, invalid, className, ...rest },
  ref,
) {
  const base =
    'h-10 w-full rounded-lg border bg-card px-3 text-sm text-ink placeholder:text-ink-muted/60 ' +
    'transition focus:outline-none focus:ring-2 disabled:opacity-50 disabled:bg-surface'
  const stateClasses = invalid
    ? 'border-danger focus:border-danger focus:ring-danger/20'
    : 'border-line focus:border-brand focus:ring-brand/20'

  if (leftIcon || rightSlot) {
    return (
      <div className="relative">
        {leftIcon && (
          <span className="pointer-events-none absolute inset-y-0 left-0 flex w-9 items-center justify-center text-ink-muted">
            {leftIcon}
          </span>
        )}
        <input
          ref={ref}
          className={cn(
            base,
            stateClasses,
            leftIcon ? 'pl-9' : null,
            rightSlot ? 'pr-9' : null,
            className,
          )}
          aria-invalid={invalid || undefined}
          {...rest}
        />
        {rightSlot && (
          <span className="absolute inset-y-0 right-0 flex w-9 items-center justify-center text-ink-muted">
            {rightSlot}
          </span>
        )}
      </div>
    )
  }

  return (
    <input
      ref={ref}
      className={cn(base, stateClasses, className)}
      aria-invalid={invalid || undefined}
      {...rest}
    />
  )
})
