import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { useAuth } from '../lib/auth'
import { asApiError } from '../lib/api'

export function LoginPage() {
  const { loginPassword, loginMfa } = useAuth()
  const nav = useNavigate()
  const [stage, setStage] = useState<'password' | 'mfa'>('password')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mfaToken, setMfaToken] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      const r = await loginPassword(email, password)
      if (r.mfa) {
        setMfaToken(r.sessionToken)
        setStage('mfa')
      } else {
        nav('/orgs', { replace: true })
      }
    } catch (err) {
      toast.error(asApiError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const submitMfa = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      await loginMfa(mfaToken, code)
      nav('/orgs', { replace: true })
    } catch (err) {
      toast.error(asApiError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen grid place-items-center bg-slate-950">
      <div className="w-full max-w-sm rounded-xl border border-slate-800 bg-slate-900/60 p-8">
        <div className="mb-6">
          <div className="text-xs uppercase tracking-widest text-slate-500">Joqarı Keńes</div>
          <div className="text-2xl font-semibold text-white">Super Admin</div>
        </div>
        {stage === 'password' ? (
          <form onSubmit={submitPassword} className="space-y-4">
            <Field label="Email">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                className="input"
              />
            </Field>
            <Field label="Password">
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                className="input"
              />
            </Field>
            <button disabled={busy} className="btn-primary w-full">
              {busy ? '...' : 'Sign in'}
            </button>
          </form>
        ) : (
          <form onSubmit={submitMfa} className="space-y-4">
            <p className="text-sm text-slate-400">
              Authenticator ilovasidan 6 ramli kod kiriting.
            </p>
            <Field label="MFA code">
              <input
                inputMode="numeric"
                pattern="[0-9]*"
                required
                maxLength={10}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoFocus
                className="input tracking-widest text-center"
              />
            </Field>
            <button disabled={busy} className="btn-primary w-full">
              {busy ? '...' : 'Verify'}
            </button>
          </form>
        )}
      </div>
      <style>{`
        .input { width: 100%; background: rgb(15 23 42); border: 1px solid rgb(51 65 85); color: white; padding: 8px 12px; border-radius: 8px; outline: none; }
        .input:focus { border-color: rgb(99 102 241); }
        .btn-primary { background: rgb(99 102 241); color: white; padding: 9px 14px; border-radius: 8px; font-weight: 600; }
        .btn-primary:hover { background: rgb(79 70 229); }
        .btn-primary:disabled { opacity: 0.5; }
      `}</style>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs uppercase tracking-widest text-slate-500 mb-1">{label}</span>
      {children}
    </label>
  )
}
