import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { useAuth } from '../lib/auth'
import { asApiError } from '../lib/api'
import { Button, Card, FormField, Input } from '../components/ui'

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
        nav('/dashboard', { replace: true })
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
      nav('/dashboard', { replace: true })
    } catch (err) {
      toast.error(asApiError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-surface px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <img src="/gerb.png" alt="" className="mb-3 h-14 w-14 object-contain" />
          <div className="text-[11px] font-semibold uppercase tracking-widest text-ink-muted">
            Хокимият
          </div>
          <div className="mt-1 text-2xl font-semibold text-brand">
            Панель управления
          </div>
        </div>
        <Card padding="loose">
          {stage === 'password' ? (
            <form onSubmit={submitPassword} className="space-y-4">
              <FormField label="Email" htmlFor="email">
                <Input
                  id="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="username"
                  autoFocus
                />
              </FormField>
              <FormField label="Пароль" htmlFor="password">
                <Input
                  id="password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                />
              </FormField>
              <Button type="submit" loading={busy} className="w-full" size="lg">
                Войти
              </Button>
            </form>
          ) : (
            <form onSubmit={submitMfa} className="space-y-4">
              <p className="text-sm text-ink-muted">
                Введите 6-значный код из приложения Authenticator.
              </p>
              <FormField label="MFA код" htmlFor="mfa">
                <Input
                  id="mfa"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  required
                  maxLength={10}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  autoFocus
                  className="text-center tracking-widest"
                />
              </FormField>
              <Button type="submit" loading={busy} className="w-full" size="lg">
                Подтвердить
              </Button>
            </form>
          )}
        </Card>
      </div>
    </div>
  )
}
