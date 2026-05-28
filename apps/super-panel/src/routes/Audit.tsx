import { useQuery } from '@tanstack/react-query'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api } from '../lib/api'

interface AuditRow {
  id: string
  actor_user_id: string | null
  actor_org_id: string | null
  action: string
  entity_type: string
  entity_id: string
  ip_address: string
  user_agent: string
  created_at: string
}

export function AuditPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['audit'],
    queryFn: async () => (await api.get<{ items: AuditRow[]; total: number }>('/api/super/audit?limit=200')).data,
  })

  return (
    <Layout>
      <PageHeader title="Audit Log" description="Hamma write-amallar bu yerda yoziladi." />
      <div className="px-8 py-6">
        {isLoading ? (
          <div className="text-slate-400">Loading...</div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800 text-sm">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <Th>When</Th>
                  <Th>Action</Th>
                  <Th>Entity</Th>
                  <Th>Actor</Th>
                  <Th>IP</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 font-mono text-xs">
                {data?.items.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-900/40">
                    <Td>{new Date(a.created_at).toLocaleString()}</Td>
                    <Td>{a.action}</Td>
                    <Td>
                      {a.entity_type ? `${a.entity_type}/${a.entity_id.slice(0, 8)}` : '—'}
                    </Td>
                    <Td>{a.actor_user_id?.slice(0, 8) ?? '—'}</Td>
                    <Td>{a.ip_address}</Td>
                  </tr>
                ))}
                {(!data || data.items.length === 0) && (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-slate-500">
                      Yozuv yo'q
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-3 text-left text-xs uppercase tracking-widest font-medium">{children}</th>
}
function Td({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-4 py-3 ${className}`}>{children}</td>
}
