import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './lib/auth'
import { LoginPage } from './routes/Login'
import { DashboardPage } from './routes/Dashboard'
import { ApplicationsPage, ApplicationDetailPage } from './routes/Applications'
import { AppointmentsPage, AppointmentDetailPage } from './routes/Appointments'
import { SessionsPage, SessionDetailPage } from './routes/Sessions'
import { StaffPage } from './routes/Staff'
import { OfficialsPage } from './routes/Officials'
import { ProfilePage } from './routes/Profile'
// QabulBook (online appointment booking) is intentionally not imported —
// the route is disabled May 2026 per operator's decision so the kiosk is
// the only booking surface and the per-day 25-visitor cap has one funnel.
// The file is preserved at routes/public/QabulBook.tsx for quick revert.
import QabulVerifyPage from './routes/public/QabulVerify'
import { I18nProvider } from './routes/public/i18n'

const ADMIN_ROLES = new Set(['org_admin', 'reviewer'])
const ADMIN_ONLY_ROLES = new Set(['org_admin'])

function Protected({
  children,
  adminOnly = false,
}: {
  children: React.ReactNode
  adminOnly?: boolean
}) {
  const { me, loading } = useAuth()
  if (loading) {
    return (
      <div className="grid h-screen place-items-center bg-surface text-ink-muted">
        Загрузка...
      </div>
    )
  }
  if (!me) return <Navigate to="/login" replace />
  if (!ADMIN_ROLES.has(me.role)) {
    return (
      <div className="grid h-screen place-items-center bg-surface px-6 text-center text-ink">
        У вас нет доступа к панели Кенеса.
      </div>
    )
  }
  if (adminOnly && !ADMIN_ONLY_ROLES.has(me.role)) {
    // Reviewer hit an admin-only route — bounce to their default landing.
    return <Navigate to="/applications" replace />
  }
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      {/* Public auth-less routes — must be matched before the protected fallback.
          Online booking (/p/:slug/qabul) is disabled — see top of file. The
          verify route stays live because kiosk-printed QR codes still need
          it for citizens to confirm their booking. */}
      <Route
        path="/p/qabul/verify/:token"
        element={<I18nProvider><QabulVerifyPage /></I18nProvider>}
      />

      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      {/* Admin-only — reviewers don't see these. */}
      <Route path="/dashboard" element={<Protected adminOnly><DashboardPage /></Protected>} />
      <Route path="/sessions" element={<Protected adminOnly><SessionsPage /></Protected>} />
      <Route path="/sessions/:id" element={<Protected adminOnly><SessionDetailPage /></Protected>} />
      <Route path="/staff" element={<Protected adminOnly><StaffPage /></Protected>} />
      <Route path="/officials" element={<Protected adminOnly><OfficialsPage /></Protected>} />
      {/* Shared (admin + reviewer). Reviewers see only their assigned rows. */}
      <Route path="/applications" element={<Protected><ApplicationsPage /></Protected>} />
      <Route path="/applications/:id" element={<Protected><ApplicationDetailPage /></Protected>} />
      <Route path="/appointments" element={<Protected><AppointmentsPage /></Protected>} />
      <Route path="/appointments/:id" element={<Protected><AppointmentDetailPage /></Protected>} />
      <Route path="/profile" element={<Protected><ProfilePage /></Protected>} />
    </Routes>
  )
}
