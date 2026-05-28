import type { ReactNode } from 'react'
import { cn } from './cn'

interface FormFieldProps {
  label?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  required?: boolean
  className?: string
  htmlFor?: string
  children: ReactNode
}

export function FormField({
  label,
  hint,
  error,
  required,
  className,
  htmlFor,
  children,
}: FormFieldProps) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {label && (
        <label
          htmlFor={htmlFor}
          className="text-xs font-medium uppercase tracking-wider text-ink-muted"
        >
          {label}
          {required && <span className="ml-1 text-danger">*</span>}
        </label>
      )}
      {children}
      {error ? (
        <p className="text-xs text-danger">{error}</p>
      ) : hint ? (
        <p className="text-xs text-ink-muted/80">{hint}</p>
      ) : null}
    </div>
  )
}
