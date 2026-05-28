import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { api } from '../api/client'

type Session = {
  id: number
  session_id: string
  started_at: string
  ended_at: string | null
  duration_seconds: number | null
  transcript: string
  error: string | null
  provider: string
  model: string | null
}

export default function SessionsPage() {
  const [selected, setSelected] = useState<Session | null>(null)
  const { data, isLoading } = useQuery<{ items: Session[] }>({
    queryKey: ['sessions'],
    queryFn: async () => (await api.get('/sessions/')).data,
    refetchInterval: 5000,
  })

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white">Sessions</h1>
      <p className="text-sm text-neutral-500 mt-1">Kiosk voice conversations</p>

      <div className="mt-6 bg-panel border border-border rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-sm text-neutral-500">Loading…</div>
        ) : data?.items.length ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-neutral-500 border-b border-border">
                <th className="text-left px-4 py-2 font-medium">Session ID</th>
                <th className="text-left px-4 py-2 font-medium">Started</th>
                <th className="text-left px-4 py-2 font-medium">Duration</th>
                <th className="text-left px-4 py-2 font-medium">Model</th>
                <th className="text-left px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((s) => (
                <tr
                  key={s.id}
                  onClick={() => setSelected(s)}
                  className="border-b border-border last:border-0 hover:bg-border/30 cursor-pointer"
                >
                  <td className="px-4 py-2 font-mono text-xs text-neutral-400">{s.session_id}</td>
                  <td className="px-4 py-2 text-neutral-400">
                    {new Date(s.started_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-neutral-400">
                    {s.duration_seconds != null ? `${s.duration_seconds}s` : '—'}
                  </td>
                  <td className="px-4 py-2 text-neutral-400">{s.model || '—'}</td>
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

      {selected && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-50"
          onClick={() => setSelected(null)}
        >
          <div
            className="bg-panel border border-border rounded-lg w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-border">
              <div>
                <div className="text-sm font-semibold text-white">{selected.session_id}</div>
                <div className="text-xs text-neutral-500 mt-0.5">
                  {new Date(selected.started_at).toLocaleString()} ·{' '}
                  {selected.duration_seconds != null ? `${selected.duration_seconds}s` : '—'}
                </div>
              </div>
              <button
                onClick={() => setSelected(null)}
                className="text-neutral-500 hover:text-white"
              >
                <X size={20} />
              </button>
            </div>
            <div className="flex-1 overflow-auto p-5">
              {selected.error && (
                <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded text-sm text-red-400">
                  {selected.error}
                </div>
              )}
              <pre className="text-sm text-neutral-300 whitespace-pre-wrap font-mono">
                {selected.transcript || '(no transcript)'}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
