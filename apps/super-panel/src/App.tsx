import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './lib/auth'
import { LoginPage } from './routes/Login'
import { OrgsPage } from './routes/Orgs'
import { OrgDetailPage } from './routes/OrgDetail'
import { UsersPage } from './routes/Users'
import { DevicesPage } from './routes/Devices'
import { AuditPage } from './routes/Audit'
import { AiDefaultsPage } from './routes/AiDefaults'
import { ReleasesPage } from './routes/Releases'
import { SettingsPage } from './routes/SettingsPage'

function Protected({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) {
    return <div className="grid h-screen place-items-center text-slate-500">Loading...</div>
  }
  if (!me) return <Navigate to="/login" replace />
  if (me.role !== 'super_admin') {
    return (
      <div className="grid h-screen place-items-center text-slate-300">
        Sizda super admin huquqi yo'q.
      </div>
    )
  }
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<Navigate to="/orgs" replace />} />
      <Route
        path="/orgs"
        element={
          <Protected>
            <OrgsPage />
          </Protected>
        }
      />
      <Route
        path="/orgs/:id"
        element={
          <Protected>
            <OrgDetailPage />
          </Protected>
        }
      />
      <Route
        path="/users"
        element={
          <Protected>
            <UsersPage />
          </Protected>
        }
      />
      <Route
        path="/devices"
        element={
          <Protected>
            <DevicesPage />
          </Protected>
        }
      />
      <Route
        path="/audit"
        element={
          <Protected>
            <AuditPage />
          </Protected>
        }
      />
      <Route
        path="/releases"
        element={
          <Protected>
            <ReleasesPage />
          </Protected>
        }
      />
      <Route
        path="/ai-defaults"
        element={
          <Protected>
            <AiDefaultsPage />
          </Protected>
        }
      />
      <Route
        path="/settings"
        element={
          <Protected>
            <SettingsPage />
          </Protected>
        }
      />
    </Routes>
  )
}
