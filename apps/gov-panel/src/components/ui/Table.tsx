import type {
  HTMLAttributes,
  TableHTMLAttributes,
  TdHTMLAttributes,
  ThHTMLAttributes,
} from 'react'
import { cn } from './cn'

export function Table({
  className,
  children,
  ...rest
}: TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-hidden rounded-card border border-line bg-card shadow-card">
      <table
        className={cn('min-w-full divide-y divide-line text-sm', className)}
        {...rest}
      >
        {children}
      </table>
    </div>
  )
}

export function THead({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn('bg-surface/60 text-ink-muted', className)}
      {...rest}
    >
      {children}
    </thead>
  )
}

export function TBody({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <tbody
      className={cn('divide-y divide-line bg-card', className)}
      {...rest}
    >
      {children}
    </tbody>
  )
}

interface TRProps extends HTMLAttributes<HTMLTableRowElement> {
  interactive?: boolean
}

export function TR({ interactive, className, children, ...rest }: TRProps) {
  return (
    <tr
      className={cn(
        interactive && 'cursor-pointer hover:bg-brand/5 transition',
        className,
      )}
      {...rest}
    >
      {children}
    </tr>
  )
}

export function TH({
  className,
  children,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        'px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider',
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  )
}

export function TD({
  className,
  children,
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cn('px-4 py-3 text-ink', className)} {...rest}>
      {children}
    </td>
  )
}
