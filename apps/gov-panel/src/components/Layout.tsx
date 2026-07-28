import { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Inbox,
  Headphones,
  Users,
  User,
  LogOut,
  CalendarCheck,
  UserCog,
  RefreshCw,
  BookOpen,
} from 'lucide-react'
import { isReviewer, useAuth } from '../lib/auth'
import { cn } from './ui/cn'

interface Props {
  children: ReactNode
}

const ADMIN_NAV = [
  { to: '/dashboard', label: 'Дашборд', icon: LayoutDashboard },
  { to: '/applications', label: 'Обращения', icon: Inbox },
  { to: '/appointments', label: 'Приёмы', icon: CalendarCheck },
  { to: '/leadership', label: 'Руководство', icon: UserCog },
  { to: '/books', label: 'Библиотека', icon: BookOpen },
  { to: '/sessions', label: 'Сессии', icon: Headphones },
  { to: '/staff', label: 'Сотрудники', icon: Users },
  { to: '/hemis', label: 'HEMIS', icon: RefreshCw },
  { to: '/profile', label: 'Профиль', icon: User },
]

const REVIEWER_NAV = [
  { to: '/applications', label: 'Обращения', icon: Inbox },
  { to: '/appointments', label: 'Приёмы', icon: CalendarCheck },
  { to: '/profile', label: 'Профиль', icon: User },
]

export function Layout({ children }: Props) {
  const { me, logout } = useAuth()
  const nav = isReviewer(me) ? REVIEWER_NAV : ADMIN_NAV
  return (
    <div className="flex h-screen bg-surface text-ink">
      <aside className="flex w-64 shrink-0 flex-col border-r border-line bg-card">
        <Link
          to={isReviewer(me) ? '/applications' : '/'}
          className="flex items-center gap-3 border-b border-line px-5 py-5 hover:bg-surface/60"
        >
          <img
            src="/gerb.png"
            alt=""
            className="h-10 w-10 shrink-0 object-contain"
          />
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
              KKMI
            </div>
            <div className="truncate text-base font-semibold text-brand">
              {isReviewer(me) ? 'Кабинет ответственного' : 'Панель управления'}
            </div>
          </div>
        </Link>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-3">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition',
                  isActive
                    ? 'bg-brand/10 text-brand'
                    : 'text-ink-muted hover:bg-surface hover:text-ink',
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="truncate">{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line px-4 py-4">
          <div className="mb-2 truncate text-xs text-ink-muted">{me?.email}</div>
          <button
            onClick={() => void logout()}
            className="inline-flex items-center gap-2 rounded-md px-2 py-1 text-sm font-medium text-ink-muted transition hover:bg-rose-50 hover:text-rose-700"
          >
            <LogOut className="h-4 w-4" />
            Выйти
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}
