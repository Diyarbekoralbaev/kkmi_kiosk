import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

export default function LogsPage() {
  const [logs, setLogs] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const preRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    let cancelled = false
    async function fetchLogs() {
      try {
        const res = await api.get('/logs/container', {
          params: { service: 'admin_ui', tail: 500 },
        })
        if (!cancelled) {
          setLogs(typeof res.data === 'string' ? res.data : JSON.stringify(res.data, null, 2))
        }
      } catch {
        if (!cancelled) setLogs('Failed to load logs')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchLogs()
    const interval = setInterval(fetchLogs, 3000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    if (preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight
    }
  }, [logs])

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white">Logs</h1>
      <p className="text-sm text-neutral-500 mt-1">admin_ui container, last 500 lines</p>

      <div className="mt-6 bg-panel border border-border rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-8 text-sm text-neutral-500">Loading…</div>
        ) : (
          <pre
            ref={preRef}
            className="p-4 text-xs text-neutral-300 font-mono max-h-[70vh] overflow-auto whitespace-pre-wrap"
          >
            {logs}
          </pre>
        )}
      </div>
    </div>
  )
}
