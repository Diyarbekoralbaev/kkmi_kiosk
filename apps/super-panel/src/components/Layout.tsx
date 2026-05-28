import { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { Building2, Users, ShieldCheck, Cpu, MonitorSmartphone, Settings, LogOut, Package } from 'lucide-react'
import { useAuth } from '../lib/auth'

interface Props {
  children: ReactNode
}

const NAV = [
  { to: '/orgs', label: 'Organizations', icon: Building2 },
  { to: '/users', label: 'Users', icon: Users },
  { to: '/devices', label: 'Devices', icon: MonitorSmartphone },
  { to: '/releases', label: 'Releases', icon: Package },
  { to: '/ai-defaults', label: 'AI Defaults', icon: Cpu },
  { to: '/audit', label: 'Audit Log', icon: ShieldCheck },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Layout({ children }: Props) {
  const { me, logout } = useAuth()
  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      <aside className="w-64 border-r border-slate-800 bg-slate-900/50 flex flex-col">
        <div className="px-6 py-6 border-b border-slate-800">
          <Link to="/" className="block">
            <div className="text-xs uppercase tracking-widest text-slate-500">Kiosk Gov</div>
            <div className="text-lg font-semibold text-slate-100">Super Admin</div>
          </Link>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition ${
                  isActive
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/50'
                }`
              }
            >
              <Icon className="w-4 h-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-4 border-t border-slate-800">
          <div className="mb-2 text-xs text-slate-500 truncate">{me?.email}</div>
          <button
            onClick={() => void logout()}
            className="flex items-center gap-2 text-sm text-slate-400 hover:text-rose-400"
          >
            <LogOut className="w-4 h-4" /> Logout
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}
