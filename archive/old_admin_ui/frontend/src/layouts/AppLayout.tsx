import { Outlet, NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  FileCode,
  MessagesSquare,
  ScrollText,
  Wrench,
  Server,
  Settings,
  LogOut,
} from 'lucide-react'
import { useAuth } from '../hooks/useAuth'

const links = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', end: true },
  { to: '/config', icon: FileCode, label: 'Config' },
  { to: '/sessions', icon: MessagesSquare, label: 'Sessions' },
  { to: '/logs', icon: ScrollText, label: 'Logs' },
  { to: '/tools', icon: Wrench, label: 'Tools' },
  { to: '/mcp', icon: Server, label: 'MCP' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export default function AppLayout() {
  const { logout } = useAuth()

  return (
    <div className="flex h-full">
      <aside className="w-56 bg-panel border-r border-border flex flex-col">
        <div className="px-5 py-5 border-b border-border">
          <div className="text-lg font-semibold text-white">Kiosk Gov</div>
          <div className="text-xs text-neutral-500 mt-0.5">Voice Agent Admin</div>
        </div>
        <nav className="flex-1 px-2 py-3 space-y-0.5">
          {links.map(({ to, icon: Icon, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition ${
                  isActive
                    ? 'bg-accent/15 text-white'
                    : 'text-neutral-400 hover:bg-border/60 hover:text-white'
                }`
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
        <button
          onClick={logout}
          className="m-3 flex items-center gap-2 px-3 py-2 rounded-md text-sm text-neutral-400 hover:bg-border/60 hover:text-white transition"
        >
          <LogOut size={16} />
          Logout
        </button>
      </aside>
      <main className="flex-1 overflow-auto">
        <div className="p-8 max-w-6xl mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
