import { forwardRef, type SelectHTMLAttributes } from 'react'
import { cn } from './cn'

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  invalid?: boolean
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { invalid, className, children, ...rest },
  ref,
) {
  return (
    <select
      ref={ref}
      className={cn(
        'h-10 w-full appearance-none rounded-lg border bg-card pl-3 pr-9 text-sm text-ink',
        'transition focus:outline-none focus:ring-2 disabled:opacity-50 disabled:bg-surface',
        'bg-[length:14px] bg-no-repeat bg-[right_12px_center]',
        // Chevron SVG inlined as background image
        "bg-[url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%235a6b85' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E\")]",
        invalid
          ? 'border-danger focus:border-danger focus:ring-danger/20'
          : 'border-line focus:border-brand focus:ring-brand/20',
        className,
      )}
      aria-invalid={invalid || undefined}
      {...rest}
    >
      {children}
    </select>
  )
})
