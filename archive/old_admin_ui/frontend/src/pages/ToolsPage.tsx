import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export default function ToolsPage() {
  const { data, isLoading, error } = useQuery<any>({
    queryKey: ['tools'],
    queryFn: async () => (await api.get('/tools/catalog')).data,
  })

  const items = Array.isArray(data) ? data : data?.tools || []

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white">Tools</h1>
      <p className="text-sm text-neutral-500 mt-1">Registered agent tools</p>

      <div className="mt-6 bg-panel border border-border rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-sm text-neutral-500">Loading…</div>
        ) : error ? (
          <div className="p-8 text-sm text-neutral-500">
            Tools API not available (yet). The kiosk uses whatever is registered in
            src/tools/registry.py.
          </div>
        ) : items.length ? (
          <ul className="divide-y divide-border">
            {items.map((t: any) => (
              <li key={t.name} className="px-5 py-3">
                <div className="font-mono text-sm text-white">{t.name}</div>
                {t.description && (
                  <div className="text-xs text-neutral-500 mt-1">{t.description}</div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <div className="p-8 text-sm text-neutral-500">No tools registered</div>
        )}
      </div>
    </div>
  )
}
