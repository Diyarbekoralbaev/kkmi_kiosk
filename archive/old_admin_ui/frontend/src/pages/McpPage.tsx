import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export default function McpPage() {
  const { data, isLoading, error } = useQuery<any>({
    queryKey: ['mcp'],
    queryFn: async () => (await api.get('/mcp/status')).data,
  })

  const servers = Array.isArray(data) ? data : data?.servers || []

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white">MCP</h1>
      <p className="text-sm text-neutral-500 mt-1">Model Context Protocol servers</p>

      <div className="mt-6 bg-panel border border-border rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-sm text-neutral-500">Loading…</div>
        ) : error ? (
          <div className="p-8 text-sm text-neutral-500">
            No MCP servers configured. Configure them under <code>mcp:</code> in ai-agent.yaml.
          </div>
        ) : servers.length ? (
          <ul className="divide-y divide-border">
            {servers.map((s: any) => (
              <li key={s.name} className="px-5 py-3 flex items-center justify-between">
                <div>
                  <div className="font-mono text-sm text-white">{s.name}</div>
                  {s.transport && (
                    <div className="text-xs text-neutral-500 mt-1">{s.transport}</div>
                  )}
                </div>
                <span
                  className={`text-xs px-2 py-0.5 rounded ${
                    s.status === 'connected'
                      ? 'bg-emerald-500/15 text-emerald-400'
                      : 'bg-neutral-500/15 text-neutral-400'
                  }`}
                >
                  {s.status || 'unknown'}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="p-8 text-sm text-neutral-500">No MCP servers configured</div>
        )}
      </div>
    </div>
  )
}
