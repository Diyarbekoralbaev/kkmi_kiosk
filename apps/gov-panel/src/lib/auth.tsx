import { createContext, ReactNode, useContext, useEffect, useState } from 'react'
import { api, clearTokens, loadTokens, saveTokens, Tokens } from './api'

export type Role = 'super_admin' | 'org_admin' | 'reviewer'

export interface Me {
  id: string
  email: string
  full_name: string
  role: Role
  org_id: string | null
  totp_enabled: boolean
  password_must_change: boolean
}

export function isReviewer(me: Me | null): boolean {
  return me?.role === 'reviewer'
}

export function isOrgAdmin(me: Me | null): boolean {
  return me?.role === 'org_admin'
}

interface AuthCtx {
  me: Me | null
  loading: boolean
  loginPassword: (email: string, password: string) => Promise<{ mfa: false } | { mfa: true; sessionToken: string }>
  loginMfa: (sessionToken: string, code: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const t = loadTokens()
    if (!t) {
      setLoading(false)
      return
    }
    api
      .get<Me>('/api/auth/me')
      .then((r) => setMe(r.data))
      .catch(() => clearTokens())
      .finally(() => setLoading(false))
  }, [])

  const loginPassword = async (email: string, password: string) => {
    const res = await api.post('/api/auth/login', { email, password })
    if (res.data.mfa_required) {
      return { mfa: true as const, sessionToken: res.data.mfa_session_token }
    }
    saveTokens({
      access_token: res.data.access_token,
      refresh_token: res.data.refresh_token,
    } as Tokens)
    setMe(res.data.user as Me)
    return { mfa: false as const }
  }

  const loginMfa = async (sessionToken: string, code: string) => {
    const res = await api.post('/api/auth/mfa/verify', {
      mfa_session_token: sessionToken,
      code,
    })
    saveTokens({
      access_token: res.data.access_token,
      refresh_token: res.data.refresh_token,
    })
    setMe(res.data.user as Me)
  }

  const logout = async () => {
    const t = loadTokens()
    if (t?.refresh_token) {
      try {
        await api.post('/api/auth/logout', { refresh_token: t.refresh_token })
      } catch {
        /* ignore */
      }
    }
    clearTokens()
    setMe(null)
  }

  const refresh = async () => {
    const r = await api.get<Me>('/api/auth/me')
    setMe(r.data)
  }

  return (
    <Ctx.Provider value={{ me, loading, loginPassword, loginMfa, logout, refresh }}>
      {children}
    </Ctx.Provider>
  )
}

export function useAuth() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth must be used within AuthProvider')
  return v
}
