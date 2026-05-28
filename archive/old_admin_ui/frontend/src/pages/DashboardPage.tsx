import { useQuery } from '@tanstack/react-query'
import { Activity, Clock, AlertCircle, MessagesSquare } from 'lucide-react'
import { api } from '../api/client'

type Metrics = {
  today_sessions: number
  avg_duration_seconds: number
  today_errors: number
  total_sessions: number
  recent_sessions: Array<{
    id: number
    session_id: string
    started_at: string
    duration_seconds: number | null
    error: string | null
  }>
}

function MetricCard({ icon: Icon, label, value, hint }: any) {
  return (
    <div className="bg-panel border border-border rounded-lg p-5">
      <div className="flex items-center gap-2 text-neutral-500 text-xs uppercase tracking-wide">
        <Icon size={14} />
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
      {hint && <div className="mt-1 text-xs text-neutral-500">{hint}</div>}
    </div>
  )
}

export default function DashboardPage() {
  const { data, isLoading } = useQuery<Metrics>({
    queryKey: ['metrics'],
    queryFn: async () => (await api.get('/sessions/metrics')).data,
    refetchInterval: 5000,
  })

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white">Dashboard</h1>
      <p className="text-sm text-neutral-500 mt-1">Kiosk voice agent overview</p>

      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          icon={MessagesSquare}
          label="Today's sessions"
          value={isLoading ? '—' : data?.today_sessions ?? 0}
        />
        <MetricCard
          icon={Clock}
          label="Avg duration"
          value={isLoading ? '—' : `${data?.avg_duration_seconds ?? 0}s`}
        />
        <MetricCard
          icon={AlertCircle}
          label="Errors today"
          value={isLoading ? '—' : data?.today_errors ?? 0}
        />
        <MetricCard
          icon={Activity}
          label="Total sessions"
          value={isLoading ? '—' : data?.total_sessions ?? 0}
        />
      </div>

      <div className="mt-8">
        <h2 className="text-sm font-semibold text-white mb-3">Recent sessions</h2>
        <div className="bg-panel border border-border rounded-lg overflow-hidden">
          {data?.recent_sessions?.length ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-neutral-500 border-b border-border">
                  <th className="text-left px-4 py-2 font-medium">Session</th>
                  <th className="text-left px-4 py-2 font-medium">Started</th>
                  <th className="text-left px-4 py-2 font-medium">Duration</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_sessions.map((s) => (
                  <tr key={s.id} className="border-b border-border last:border-0">
                    <td className="px-4 py-2 font-mono text-xs text-neutral-400">{s.session_id}</td>
                    <td className="px-4 py-2 text-neutral-400">
                      {new Date(s.started_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2 text-neutral-400">
                      {s.duration_seconds != null ? `${s.duration_seconds}s` : '—'}
                    </td>
                    <td className="px-4 py-2">
                      {s.error ? (
                        <span className="text-red-400">Error</span>
                      ) : (
                        <span className="text-emerald-400">OK</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-8 text-center text-sm text-neutral-500">No sessions yet</div>
          )}
        </div>
      </div>
    </div>
  )
}
