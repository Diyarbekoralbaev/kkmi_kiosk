import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

export function SettingsPage() {
  const { me, refresh } = useAuth()
  const qc = useQueryClient()

  const setupQ = useQuery({
    queryKey: ['mfa-setup'],
    queryFn: async () => (await api.post<{ secret: string; otpauth_uri: string }>('/api/auth/mfa/setup')).data,
    enabled: false,
  })

  const enable = useMutation({
    mutationFn: async (code: string) => api.post('/api/auth/mfa/enable', { code }),
    onSuccess: async () => {
      toast.success('MFA enabled')
      await refresh()
      qc.removeQueries({ queryKey: ['mfa-setup'] })
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  const change = useMutation({
    mutationFn: async (vars: { current: string; next: string }) =>
      api.post('/api/auth/password/change', {
        current_password: vars.current,
        new_password: vars.next,
      }),
    onSuccess: () => toast.success('Password changed'),
    onError: (err) => toast.error(asApiError(err).message),
  })

  const [code, setCode] = useState('')
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')

  return (
    <Layout>
      <PageHeader title="Settings" description="Profil va xavfsizlik sozlamalari." />
      <div className="px-8 py-6 space-y-6 max-w-xl">
        <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-6">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-slate-400">Profil</h2>
          <div className="text-sm text-slate-300 space-y-1">
            <div><span className="text-slate-500">Email:</span> {me?.email}</div>
            <div><span className="text-slate-500">Role:</span> {me?.role}</div>
            <div><span className="text-slate-500">MFA:</span> {me?.totp_enabled ? 'enabled' : 'disabled'}</div>
          </div>
        </section>
        {!me?.totp_enabled && (
          <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-6">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-slate-400">MFA setup</h2>
            <p className="text-xs text-slate-500 mb-3">
              Super admin uchun MFA majburiy. Authenticator ilovasiga (Google Authenticator, Authy, ...) qo'shing.
            </p>
            {!setupQ.data ? (
              <button
                onClick={() => setupQ.refetch()}
                disabled={setupQ.isFetching}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
              >
                {setupQ.isFetching ? '...' : 'Generate secret'}
              </button>
            ) : (
              <div className="space-y-3">
                <code className="block rounded bg-slate-900 border border-slate-800 px-3 py-2 font-mono text-sm break-all">
                  {setupQ.data.secret}
                </code>
                <code className="block rounded bg-slate-900 border border-slate-800 px-3 py-2 font-mono text-xs break-all">
                  {setupQ.data.otpauth_uri}
                </code>
                <input
                  className="input"
                  placeholder="6-raqamli kod"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
                <button onClick={() => enable.mutate(code)} disabled={enable.isPending} className="btn-primary w-full">
                  {enable.isPending ? '...' : 'Enable MFA'}
                </button>
              </div>
            )}
          </section>
        )}
        <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-6">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-slate-400">Password</h2>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              change.mutate({ current, next })
              setCurrent('')
              setNext('')
            }}
            className="space-y-3"
          >
            <input className="input" type="password" placeholder="Current" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            <input className="input" type="password" placeholder="New (>= 10 chars)" value={next} onChange={(e) => setNext(e.target.value)} required minLength={10} />
            <button disabled={change.isPending} className="btn-primary w-full">
              {change.isPending ? '...' : "O'zgartirish"}
            </button>
          </form>
        </section>
      </div>
      <style>{`
        .input { width: 100%; background: rgb(15 23 42); border: 1px solid rgb(51 65 85); color: white; padding: 8px 12px; border-radius: 8px; outline: none; }
        .input:focus { border-color: rgb(99 102 241); }
        .btn-primary { background: rgb(99 102 241); color: white; padding: 8px 14px; border-radius: 8px; font-weight: 600; }
        .btn-primary:hover { background: rgb(79 70 229); }
        .btn-primary:disabled { opacity: 0.5; }
      `}</style>
    </Layout>
  )
}
