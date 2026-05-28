import { useCallback, useState } from 'react'
import { api } from '../api/client'

export function useAuth() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('kiosk_token'))

  const login = useCallback(async (username: string, password: string) => {
    const form = new URLSearchParams()
    form.append('username', username)
    form.append('password', password)
    const res = await api.post('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    const t = res.data.access_token
    localStorage.setItem('kiosk_token', t)
    setToken(t)
    return t
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('kiosk_token')
    setToken(null)
    window.location.href = '/login'
  }, [])

  return { token, login, logout }
}
