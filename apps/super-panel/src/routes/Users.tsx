import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { Plus, KeyRound } from 'lucide-react'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'

interface UserRow {
  id: string
  email: string
  full_name: string
  role: string
  org_id: string | null
  status: string
  totp_enabled: boolean
  password_must_change: boolean
  created_at: string
}

interface UsersResp {
  items: UserRow[]
  total: number
}

interface OrgRow {
  id: string
  name: string
  slug: string
}

export function UsersPage() {
  const [showCreate, setShowCreate] = useState(false)
  const [tempPassword, setTempPassword] = useState<{ user: string; pwd: string } | null>(null)

  const users = useQuery({
    queryKey: ['users'],
    queryFn: async () => (await api.get<UsersResp>('/api/super/users')).data,
  })
  const orgs = useQuery({
    queryKey: ['orgs-min'],
    queryFn: async () => (await api.get<{ items: OrgRow[] }>('/api/super/orgs')).data.items,
  })

  return (
    <Layout>
      <PageHeader
        title="Users"
        description="Super adminlar va org admin akkawntlar."
        actions={
          <button onClick={() => setShowCreate(true)} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500">
            <Plus className="w-4 h-4" /> Yangi user
          </button>
        }
      />
      <div className="px-8 py-6">
        {users.isLoading ? (
          <div className="text-slate-400">Loading...</div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800 text-sm">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <Th>Email</Th>
                  <Th>Name</Th>
                  <Th>Role</Th>
                  <Th>Org</Th>
                  <Th>Status</Th>
                  <Th>MFA</Th>
                  <Th>Actions</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {users.data?.items.map((u) => (
                  <UserRowItem
                    key={u.id}
                    user={u}
                    orgs={orgs.data ?? []}
                    onTempPassword={(pwd) => setTempPassword({ user: u.email, pwd })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {showCreate && <CreateUserModal orgs={orgs.data ?? []} onClose={() => setShowCreate(false)} onCreated={(p) => setTempPassword({ user: p.email, pwd: p.temp_password })} />}
      {tempPassword && (
        <TempPasswordModal email={tempPassword.user} password={tempPassword.pwd} onClose={() => setTempPassword(null)} />
      )}
    </Layout>
  )
}

function UserRowItem({ user, orgs, onTempPassword }: { user: UserRow; orgs: OrgRow[]; onTempPassword: (pwd: string) => void }) {
  const qc = useQueryClient()
  const toggleStatus = useMutation({
    mutationFn: async () => {
      await api.patch(`/api/super/users/${user.id}`, {
        status: user.status === 'active' ? 'disabled' : 'active',
      })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
    onError: (err) => toast.error(asApiError(err).message),
  })
  const reset = useMutation({
    mutationFn: async () => (await api.post<{ temp_password: string }>(`/api/super/users/${user.id}/password/reset`)).data,
    onSuccess: (d) => onTempPassword(d.temp_password),
    onError: (err) => toast.error(asApiError(err).message),
  })
  const orgName = user.org_id ? orgs.find((o) => o.id === user.org_id)?.name ?? user.org_id : '—'
  return (
    <tr className="hover:bg-slate-900/40">
      <Td>{user.email}</Td>
      <Td>{user.full_name || '—'}</Td>
      <Td className="capitalize">{user.role.replace('_', ' ')}</Td>
      <Td>{orgName}</Td>
      <Td>
        <button
          onClick={() => toggleStatus.mutate()}
          className={`rounded-full border px-2 py-0.5 text-xs ${
            user.status === 'active'
              ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
              : 'border-rose-500/40 bg-rose-500/15 text-rose-300'
          }`}
        >
          {user.status}
        </button>
      </Td>
      <Td>{user.totp_enabled ? 'on' : 'off'}</Td>
      <Td>
        <button
          onClick={() => reset.mutate()}
          disabled={reset.isPending}
          className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300"
        >
          <KeyRound className="w-3 h-3" /> Reset password
        </button>
      </Td>
    </tr>
  )
}

function CreateUserModal({ orgs, onClose, onCreated }: { orgs: OrgRow[]; onClose: () => void; onCreated: (p: { email: string; temp_password: string }) => void }) {
  const qc = useQueryClient()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<'super_admin' | 'org_admin'>('org_admin')
  const [orgId, setOrgId] = useState<string>(orgs[0]?.id ?? '')

  const create = useMutation({
    mutationFn: async () =>
      (
        await api.post<{ email: string; temp_password: string }>('/api/super/users', {
          email,
          full_name: name,
          role,
          org_id: role === 'org_admin' ? orgId : null,
        })
      ).data,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['users'] })
      onCreated(data)
      onClose()
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  return (
    <ModalSimple onClose={onClose} title="Yangi user">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate()
        }}
        className="space-y-3"
      >
        <input className="input" type="email" required placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="input" placeholder="full name" value={name} onChange={(e) => setName(e.target.value)} />
        <select className="input" value={role} onChange={(e) => setRole(e.target.value as 'super_admin' | 'org_admin')}>
          <option value="org_admin">org_admin</option>
          <option value="super_admin">super_admin</option>
        </select>
        {role === 'org_admin' && (
          <select className="input" value={orgId} onChange={(e) => setOrgId(e.target.value)} required>
            <option value="">— org tanlang —</option>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        )}
        <button disabled={create.isPending} className="btn-primary w-full">
          {create.isPending ? '...' : 'Yaratish'}
        </button>
      </form>
    </ModalSimple>
  )
}

function TempPasswordModal({ email, password, onClose }: { email: string; password: string; onClose: () => void }) {
  return (
    <ModalSimple onClose={onClose} title="Vaqtinchalik paról">
      <div className="space-y-3">
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
          Bu paról bir martagina ko'rsatiladi. Foydalanuvchiga (email: {email}) yetkazing.
        </div>
        <code className="block rounded bg-slate-900 border border-slate-800 px-3 py-2 font-mono text-sm">{password}</code>
        <button onClick={onClose} className="btn-primary w-full">Yoping</button>
      </div>
    </ModalSimple>
  )
}

function ModalSimple({ children, onClose, title }: { children: React.ReactNode; onClose: () => void; title: string }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 px-4">
      <div className="w-full max-w-md rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">{title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white">✕</button>
        </div>
        {children}
      </div>
      <style>{`
        .input { width: 100%; background: rgb(15 23 42); border: 1px solid rgb(51 65 85); color: white; padding: 8px 12px; border-radius: 8px; outline: none; }
        .input:focus { border-color: rgb(99 102 241); }
        .btn-primary { background: rgb(99 102 241); color: white; padding: 8px 14px; border-radius: 8px; font-weight: 600; }
        .btn-primary:hover { background: rgb(79 70 229); }
        .btn-primary:disabled { opacity: 0.5; }
      `}</style>
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-3 text-left text-xs uppercase tracking-widest font-medium">{children}</th>
}
function Td({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-4 py-3 ${className}`}>{children}</td>
}
