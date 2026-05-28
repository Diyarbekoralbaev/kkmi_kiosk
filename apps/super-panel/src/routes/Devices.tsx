import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'
import { toast } from 'sonner'
import { Plus, Copy, X, Check } from 'lucide-react'

interface DeviceRow {
  id: string
  org_id: string
  name: string
  location: string
  status: string
  cert_serial: string | null
  last_seen_at: string | null
  created_at: string
}

interface OrgRow {
  id: string
  name: string
  slug: string
}

interface DeviceCreatedResponse extends DeviceRow {
  enrollment_code: string
  enrollment_expires_at: string
}

interface EnrollmentCodeResponse {
  enrollment_code: string
  enrollment_expires_at: string
}

interface EnrollmentDisplay {
  code: string
  expiresAt: string
  deviceName: string
}

export function DevicesPage() {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [enrollment, setEnrollment] = useState<EnrollmentDisplay | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['devices'],
    queryFn: async () =>
      (await api.get<{ items: DeviceRow[]; total: number }>('/api/super/devices')).data,
  })

  const { data: orgs } = useQuery({
    queryKey: ['orgs', 'all'],
    queryFn: async () =>
      (await api.get<{ items: OrgRow[]; total: number }>('/api/super/orgs?limit=200')).data,
  })

  const revoke = useMutation({
    mutationFn: async (id: string) => api.post(`/api/super/devices/${id}/revoke`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices'] }),
    onError: (err) => toast.error(asApiError(err).message),
  })

  const regenerate = useMutation({
    mutationFn: async (id: string) =>
      (
        await api.post<EnrollmentCodeResponse>(
          `/api/super/devices/${id}/enrollment-code`
        )
      ).data,
    onSuccess: (resp, id) => {
      const dev = data?.items.find((d) => d.id === id)
      setEnrollment({
        code: resp.enrollment_code,
        expiresAt: resp.enrollment_expires_at,
        deviceName: dev?.name || 'Device',
      })
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  return (
    <Layout>
      <PageHeader
        title="Devices"
        description="Hokimiyatlardagi C# kiosk client'lari. Yangi kiosk qo'shish: device yarating, 10 daqiqalik enrollment kodini kiosk'ga kirgazing."
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-500"
          >
            <Plus className="h-4 w-4" /> Yangi device
          </button>
        }
      />
      <div className="px-8 py-6">
        {isLoading ? (
          <div className="text-slate-400">Loading...</div>
        ) : data?.items.length ? (
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800 text-sm">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <Th>Name</Th>
                  <Th>Location</Th>
                  <Th>Status</Th>
                  <Th>Last seen</Th>
                  <Th>Actions</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {data.items.map((d) => (
                  <tr key={d.id} className="hover:bg-slate-900/40">
                    <Td>{d.name || '—'}</Td>
                    <Td>{d.location || '—'}</Td>
                    <Td>
                      <StatusBadge status={d.status} />
                    </Td>
                    <Td>
                      {d.last_seen_at
                        ? new Date(d.last_seen_at).toLocaleString()
                        : '—'}
                    </Td>
                    <Td>
                      <div className="flex gap-3">
                        {d.status !== 'revoked' && (
                          <button
                            onClick={() => regenerate.mutate(d.id)}
                            disabled={regenerate.isPending}
                            className="text-xs text-cyan-400 hover:text-cyan-300 disabled:opacity-50"
                          >
                            Re-enroll
                          </button>
                        )}
                        {d.status !== 'revoked' && (
                          <button
                            onClick={() => revoke.mutate(d.id)}
                            disabled={revoke.isPending}
                            className="text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50"
                          >
                            Revoke
                          </button>
                        )}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-slate-800 bg-slate-900/30 px-6 py-16 text-center">
            <div className="text-lg font-semibold text-slate-300">
              Hech qanday device yo'q
            </div>
            <div className="mt-2 text-sm text-slate-500">
              "Yangi device" tugmasi orqali kiosk qo'shing.
            </div>
          </div>
        )}
      </div>

      {showCreate && (
        <CreateDeviceModal
          orgs={orgs?.items ?? []}
          onClose={() => setShowCreate(false)}
          onCreated={(resp) => {
            setShowCreate(false)
            setEnrollment({
              code: resp.enrollment_code,
              expiresAt: resp.enrollment_expires_at,
              deviceName: resp.name,
            })
            qc.invalidateQueries({ queryKey: ['devices'] })
          }}
        />
      )}

      {enrollment && (
        <EnrollmentCodeModal
          code={enrollment.code}
          expiresAt={enrollment.expiresAt}
          deviceName={enrollment.deviceName}
          onClose={() => setEnrollment(null)}
        />
      )}
    </Layout>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'border-amber-500/30 bg-amber-500/15 text-amber-400',
    active: 'border-emerald-500/30 bg-emerald-500/15 text-emerald-400',
    revoked: 'border-rose-500/30 bg-rose-500/15 text-rose-400',
  }
  const c = colors[status] || 'border-slate-600 bg-slate-700/50 text-slate-300'
  return (
    <span className={`rounded-md border px-2 py-0.5 text-xs ${c}`}>{status}</span>
  )
}

function CreateDeviceModal({
  orgs,
  onClose,
  onCreated,
}: {
  orgs: OrgRow[]
  onClose: () => void
  onCreated: (resp: DeviceCreatedResponse) => void
}) {
  const [orgId, setOrgId] = useState(orgs[0]?.id ?? '')
  const [name, setName] = useState('')
  const [location, setLocation] = useState('')

  const create = useMutation({
    mutationFn: async () =>
      (
        await api.post<DeviceCreatedResponse>('/api/super/devices', {
          org_id: orgId,
          name,
          location,
        })
      ).data,
    onSuccess: (resp) => onCreated(resp),
    onError: (err) => toast.error(asApiError(err).message),
  })

  return (
    <ModalShell onClose={onClose} title="Yangi device yaratish">
      <div className="space-y-4">
        <Field label="Hokimiyat (org)">
          <select
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
          >
            {orgs.length === 0 && <option value="">— org yo'q —</option>}
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Nomi">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
            placeholder="Reception kiosk #1"
          />
        </Field>
        <Field label="Joylashuvi">
          <input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
            placeholder="1-qabat, qabıllaw bólmesi"
          />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            Biykar qılıw
          </button>
          <button
            disabled={!orgId || !name || create.isPending}
            onClick={() => create.mutate()}
            className="rounded-md bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
          >
            {create.isPending ? 'Jaratıp atır...' : 'Jaratıw'}
          </button>
        </div>
      </div>
    </ModalShell>
  )
}

function EnrollmentCodeModal({
  code,
  expiresAt,
  deviceName,
  onClose,
}: {
  code: string
  expiresAt: string
  deviceName: string
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error('Köshire almadıq')
    }
  }
  return (
    <ModalShell onClose={onClose} title={`Enrollment kodı — ${deviceName}`}>
      <div className="space-y-4">
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
          Bul kod tek <strong>1 márte</strong> kórsetiledi. Kioskqa kirgizip
          bolǵannan keyin bul oynanı jabıń. Múddet:{' '}
          <strong>{new Date(expiresAt).toLocaleString()}</strong>.
        </div>
        <div className="flex items-center gap-2">
          <code className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-4 py-3 text-center font-mono text-lg tracking-widest text-cyan-300">
            {code}
          </code>
          <button
            onClick={copy}
            className="rounded-md bg-slate-800 px-3 py-3 text-slate-300 hover:bg-slate-700"
            title="Köshirip alıw"
          >
            {copied ? (
              <Check className="h-4 w-4 text-emerald-400" />
            ) : (
              <Copy className="h-4 w-4" />
            )}
          </button>
        </div>
        <div className="flex justify-end pt-2">
          <button
            onClick={onClose}
            className="rounded-md bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-500"
          >
            Saqlap aldım
          </button>
        </div>
      </div>
    </ModalShell>
  )
}

function ModalShell({
  children,
  onClose,
  title,
}: {
  children: React.ReactNode
  onClose: () => void
  title: string
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-xl border border-slate-800 bg-slate-950 p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-100">{title}</h3>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </span>
      {children}
    </label>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-widest">
      {children}
    </th>
  )
}
function Td({
  children,
  className = '',
}: {
  children: React.ReactNode
  className?: string
}) {
  return <td className={`px-4 py-3 ${className}`}>{children}</td>
}
